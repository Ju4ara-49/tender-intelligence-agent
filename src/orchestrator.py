from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.ai.analyzer import TenderAnalyzer
from src.collectors.base import CollectorUnavailableError
from src.collectors.registry import get_enabled_collectors
from src.filters.keyword_filter import KeywordFilter
from src.models.tender import Tender
from src.notifications.telegram import TelegramNotifier
from src.notifications.email import EmailNotifier
from src.profiles import SearchProfileStore
from src.settings import AppSettings
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState
from src.telegram_settings import CriteriaStore, TenderCriteria
from src.export.excel import export_tenders_to_excel

logger = logging.getLogger(__name__)


class Orchestrator:
    """Широкий multi-platform pipeline: discovery → detail → filters → AI → notify."""

    def _get_next_search_number(self) -> int:
        return self.db.next_search_number()

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.db = TenderDatabase(settings.database_path)
        self.notification_state = NotificationDeliveryState(self.db)
        self.criteria_store = CriteriaStore(self.db)
        self.profile_store = SearchProfileStore(self.db)
        self.analyzer = TenderAnalyzer(
            model=settings.ai_model,
            ai_context=settings.ai_context,
            use_stub_when_no_key=settings.ai_use_stub,
            ollama_url=settings.ollama_url,
        )
        logger.info(
            "AI: provider=%s | model=%s | ollama_url=%s | configured=%s",
            settings.ai_provider,
            settings.ai_model,
            settings.ollama_url,
            self.analyzer.is_configured,
        )
        self.notifier = TelegramNotifier(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            dry_run_when_no_token=settings.telegram_dry_run,
        )
        self.email_notifier = EmailNotifier(
            enabled=settings.email_enabled,
            smtp_host=settings.email_smtp_host,
            smtp_port=settings.email_smtp_port,
            username=settings.email_from,
            password=settings.email_password,
            recipient=settings.email_to,
        )
        self._stop_requested = False
        self.last_run_results: list[Tender] = []
        self.last_platform_errors: dict[str, str] = {}

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    def request_stop(self) -> None:
        self._stop_requested = True
        logger.info("Получен запрос на остановку поиска.")

    def clear_stop_request(self) -> None:
        self._stop_requested = False

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        moscow_offset = timezone(timedelta(hours=3), name="MSK")
        return value.replace(tzinfo=moscow_offset).astimezone(timezone.utc)

    def _normalize_tender_datetimes(self, tender: Tender) -> Tender:
        tender.to_utc()
        if tender.deadline is None and tender.end_date is not None:
            tender.deadline = tender.end_date
        return tender

    @staticmethod
    def _set_detail_failure(tender: Tender, reason: str) -> Tender:
        tender.detail_status = "failed"
        tender.detail_diagnostics = str(reason)[:4000]
        tender.raw_data["details_loaded"] = False
        tender.raw_data["detail_status"] = "failed"
        tender.raw_data["detail_diagnostics"] = tender.detail_diagnostics
        return tender

    def _merge_detail(self, tender: Tender, detailed: Tender) -> Tender:
        for field_name in (
            "title", "description", "price", "currency", "start_date", "end_date",
            "deadline", "published_at", "region", "customer", "customer_inn", "law_type",
            "advance_percent", "postpayment_days", "application_security_percent",
            "contract_security_percent", "url",
        ):
            value = getattr(detailed, field_name, None)
            if value not in (None, ""):
                setattr(tender, field_name, value)
        if detailed.advance_percent is not None:
            tender.advance_required = detailed.advance_percent > 0
        elif detailed.advance_required:
            tender.advance_required = True
        if detailed.field_sources:
            tender.field_sources.update(detailed.field_sources)
            tender.raw_data["field_sources"] = dict(tender.field_sources)
        if detailed.documents:
            tender.documents = list(detailed.documents)
            tender.raw_data["documents"] = [dict(item) for item in tender.documents]
        if detailed.raw_data:
            for key in (
                "procurement_method", "application_security", "contract_security",
                "advance_payment", "postpayment", "lots", "lot", "specification",
                "specifications", "items", "products",
            ):
                if detailed.raw_data.get(key) is not None:
                    tender.raw_data[key] = detailed.raw_data[key]
            tender.raw_data["details"] = detailed.raw_data
        if tender.documents:
            tender.raw_data["documents"] = [dict(item) for item in tender.documents]
        if tender.field_sources:
            tender.raw_data["field_sources"] = dict(tender.field_sources)
        status = str(getattr(detailed, "detail_status", "success") or "success").lower()
        if status not in {"success", "partial", "failed"}:
            status = "success"
        tender.detail_status = status
        diagnostics = str(getattr(detailed, "detail_diagnostics", "") or "")
        tender.detail_diagnostics = diagnostics[:4000]
        tender.raw_data["details_loaded"] = status != "failed"
        tender.raw_data["detail_status"] = status
        if diagnostics:
            tender.raw_data["detail_diagnostics"] = diagnostics[:4000]
        return self._normalize_tender_datetimes(tender)

    def _enrich_tender(self, collector, tender: Tender) -> tuple[Tender, bool]:
        get_details = getattr(collector, "get_details", None)
        if not callable(get_details) or not tender.external_id:
            tender.detail_status = "partial"
            tender.raw_data["details_loaded"] = False
            tender.raw_data["detail_status"] = "partial"
            return self._normalize_tender_datetimes(tender), False
        try:
            logger.info(
                "%s: загружаем детали тендера %s",
                getattr(collector, "platform", "unknown"),
                tender.external_id,
            )
            detailed = get_details(tender.external_id)
            if detailed is None:
                tender = self._set_detail_failure(tender, "get_details returned None")
                return self._normalize_tender_datetimes(tender), False
            tender = self._merge_detail(tender, detailed)
            return tender, tender.detail_status == "success"
        except Exception as exc:
            logger.exception(
                "%s: ошибка загрузки деталей %s",
                getattr(collector, "platform", "unknown"),
                tender.external_id,
            )
            tender = self._set_detail_failure(tender, f"{type(exc).__name__}: {exc}")
            return self._normalize_tender_datetimes(tender), False

    @staticmethod
    def _platform_worker_count(search_config: dict, collector_count: int) -> int:
        configured = search_config.get(
            "platform_workers",
            search_config.get("concurrency", collector_count),
        )
        try:
            requested = int(configured)
        except (TypeError, ValueError):
            requested = collector_count
        return min(collector_count, max(1, requested))

    @staticmethod
    def _search_platform(collector, keywords: list[str]) -> tuple[str, list[Tender]]:
        platform = getattr(collector, "platform", "unknown")
        try:
            config = collector.config if hasattr(collector, "config") else {}
            lookback_days = int(config.get("lookback_days", 3))
            since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            found = collector.search(keywords=keywords, since=since) or []
            setattr(collector, "_last_search_error", "")
            logger.info(
                "Discovery: platform=%s keywords=%d raw=%d",
                platform,
                len(keywords),
                len(found),
            )
            return platform, list(found)
        except CollectorUnavailableError as exc:
            message = str(exc)[:4000]
            setattr(collector, "_last_search_error", message)
            logger.error("Discovery: площадка %s недоступна: %s", platform, message)
            return platform, []
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"[:4000]
            setattr(collector, "_last_search_error", message)
            logger.exception("Discovery: площадка %s завершилась ошибкой", platform)
            return platform, []

    @staticmethod
    def _deduplicate_pairs(pairs: list[tuple[object, Tender]]) -> list[tuple[object, Tender]]:
        seen: set[str] = set()
        result: list[tuple[object, Tender]] = []
        for collector, tender in pairs:
            if tender.unique_key in seen:
                continue
            seen.add(tender.unique_key)
            result.append((collector, tender))
        return result

    @staticmethod
    def _passes_criteria(tender: Tender, criteria: TenderCriteria) -> tuple[bool, str]:
        if criteria.min_price is not None and (tender.price is None or tender.price < criteria.min_price):
            return False, "min_price"
        if criteria.max_price is not None and (tender.price is None or tender.price > criteria.max_price):
            return False, "max_price"
        if criteria.advance_required:
            if not tender.advance_required:
                return False, "advance_required"
            if tender.advance_percent is None:
                return False, "advance_percent_missing"
        if criteria.min_advance_percent > 0 and (
            tender.advance_percent is None or tender.advance_percent < criteria.min_advance_percent
        ):
            return False, "min_advance_percent"
        if criteria.max_postpayment_days is not None and (
            tender.postpayment_days is None or tender.postpayment_days > criteria.max_postpayment_days
        ):
            return False, "max_postpayment_days"
        if criteria.min_application_security_percent > 0 and (
            tender.application_security_percent is None
            or tender.application_security_percent < criteria.min_application_security_percent
        ):
            return False, "min_application_security_percent"
        if criteria.max_application_security_percent is not None and (
            tender.application_security_percent is None
            or tender.application_security_percent > criteria.max_application_security_percent
        ):
            return False, "max_application_security_percent"
        if criteria.min_contract_security_percent > 0 and (
            tender.contract_security_percent is None
            or tender.contract_security_percent < criteria.min_contract_security_percent
        ):
            return False, "min_contract_security_percent"
        if criteria.max_contract_security_percent is not None and (
            tender.contract_security_percent is None
            or tender.contract_security_percent > criteria.max_contract_security_percent
        ):
            return False, "max_contract_security_percent"
        if criteria.min_submission_days and tender.deadline is not None:
            if (tender.deadline - datetime.now(timezone.utc)).total_seconds() < criteria.min_submission_days * 86400:
                return False, "min_submission_days"
        elif criteria.min_submission_days:
            return False, "deadline_missing"
        return True, ""

    @staticmethod
    def _passes_regions(tender: Tender, regions: list[str] | None) -> bool:
        if not regions:
            return True
        tender_region = (tender.region or "").strip().casefold()
        if not tender_region:
            return False
        return any(region.strip().casefold() in tender_region for region in regions if region.strip())

    def run_cycle(
        self,
        user_id: str | int | None = None,
        criteria: TenderCriteria | None = None,
        keywords: list[str] | None = None,
        platforms: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
        regions: list[str] | None = None,
        notification_recipient_key: str | None = None,
        notification_chat_id: str | None = None,
    ) -> dict[str, int]:
        search_number = self._get_next_search_number()
        stats = {
            "search_number": search_number,
            "found": 0,
            "soft_filtered": 0,
            "filtered": 0,
            "keyword_excluded": 0,
            "new": 0,
            "analyzed": 0,
            "notified": 0,
            "skipped_duplicate": 0,
            "excluded_by_criteria": 0,
            "excluded_by_region": 0,
            "details_loaded": 0,
            "details_partial": 0,
            "details_failed": 0,
            "saved": 0,
            "ai_failed": 0,
            "platform_errors": 0,
        }
        self.clear_stop_request()
        self.last_run_results = []
        self.last_platform_errors = {}
        criteria = criteria if criteria is not None else self.criteria_store.get(user_id)
        min_text = int(self.settings.config.get("filters", {}).get("min_text_length", 10))
        search_keywords = keywords if keywords is not None else (
            self.criteria_store.get_keywords(user_id) or self.settings.include_keywords
        )
        enabled_platforms = platforms if platforms is not None else self.criteria_store.get_enabled_platforms(user_id)
        exclusions = exclude_keywords if exclude_keywords is not None else criteria.exclude_keywords
        selected_regions = regions if regions is not None else criteria.regions
        recipient_key = (
            str(notification_recipient_key).strip()
            if notification_recipient_key
            else (f"user:{str(user_id).strip()}" if user_id is not None and str(user_id).strip() else NotificationDeliveryState.DEFAULT_RECIPIENT_KEY)
        )
        target_chat_id = (
            str(notification_chat_id).strip()
            if notification_chat_id
            else (str(user_id).strip() if user_id is not None and str(user_id).strip() else None)
        )
        self.keyword_filter = KeywordFilter(include=search_keywords, exclude=exclusions, min_text_length=min_text)
        collectors = get_enabled_collectors(self.settings.config, enabled_platforms=enabled_platforms)
        if not collectors:
            logger.warning("Нет включённых сборщиков. Проверьте config.yaml и настройки площадок.")
            return stats

        all_pairs: list[tuple[object, Tender]] = []
        workers = self._platform_worker_count(
            self.settings.config.get("search", {}),
            len(collectors),
        )
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="collector") as pool:
            futures = [pool.submit(self._search_platform, collector, search_keywords) for collector in collectors]
            for future in as_completed(futures):
                platform, found = future.result()
                collector = next((c for c in collectors if c.platform == platform), None)
                if collector is not None:
                    all_pairs.extend((collector, tender) for tender in found)

        self.last_platform_errors = {
            collector.platform: str(getattr(collector, "_last_search_error", "")).strip()
            for collector in collectors
            if str(getattr(collector, "_last_search_error", "")).strip()
        }
        stats["platform_errors"] = len(self.last_platform_errors)
        if self.last_platform_errors:
            for platform, error in self.last_platform_errors.items():
                logger.error("Discovery failed: platform=%s error=%s", platform, error)

        stats["found"] = len(all_pairs)
        unique_pairs = self._deduplicate_pairs(all_pairs)
        now = datetime.now(timezone.utc)
        soft_pairs = []
        for collector, tender in unique_pairs:
            if self.stop_requested:
                break
            config = self.settings.config.get("collectors", {}).get(collector.platform, {})
            since = now - timedelta(days=int(config.get("lookback_days", 3)))
            published = self._normalize_datetime(tender.published_at)
            if published is not None and published < since:
                continue
            tender = self._normalize_tender_datetimes(tender)
            if self.keyword_filter.matches_soft(tender):
                soft_pairs.append((collector, tender))
        stats["soft_filtered"] = len(soft_pairs)

        enriched_pairs = []
        for collector, tender in soft_pairs:
            if self.stop_requested:
                break
            enriched, detail_loaded = self._enrich_tender(collector, tender)
            detail_status = str(getattr(enriched, "detail_status", "partial") or "partial").lower()
            stats["details_loaded"] += int(detail_status == "success" and detail_loaded)
            stats["details_partial"] += int(detail_status == "partial")
            stats["details_failed"] += int(detail_status == "failed")
            enriched_pairs.append((collector, enriched))
            existing = self.db.exists(enriched.unique_key)
            self.db.save_tender(enriched)
            stats["saved"] += 1
            if not existing:
                stats["new"] += 1

        strict_pairs = []
        for collector, tender in enriched_pairs:
            if tender.detail_status == "failed":
                continue
            if self.keyword_filter.matches_strict(tender):
                strict_pairs.append((collector, tender))
            else:
                stats["keyword_excluded"] += 1
        stats["filtered"] = len(strict_pairs)

        export_tender_ids: list[int] = []
        for collector, tender in strict_pairs:
            if self.stop_requested:
                break
            if not self._passes_regions(tender, selected_regions):
                stats["excluded_by_region"] += 1
                continue
            passed, reason = self._passes_criteria(tender, criteria)
            if not passed:
                stats["excluded_by_criteria"] += 1
                logger.debug("Критерии: исключён %s:%s (%s)", tender.platform, tender.external_id, reason)
                continue
            self.last_run_results.append(tender)
            tender_id = self.db.get_tender_id(tender.unique_key)
            if tender_id is None:
                logger.error("Tender disappeared after save: %s", tender.unique_key)
                continue
            export_tender_ids.append(tender_id)
            if self.notification_state.was_notified(tender, recipient_key=recipient_key):
                stats["skipped_duplicate"] += 1
                continue
            try:
                analysis = self.analyzer.analyze(tender)
            except Exception as exc:
                stats["ai_failed"] += 1
                logger.exception("AI: ошибка анализа %s: %s", tender.unique_key, exc)
                continue
            self.db.save_analysis(tender_id, analysis)
            stats["analyzed"] += 1
            if analysis.relevance_score < criteria.min_ai_score:
                continue
            if self.notification_state.was_notified(tender, recipient_key=recipient_key):
                stats["skipped_duplicate"] += 1
                continue
            if self.notifier.send_tender_alert(tender, analysis, chat_id=target_chat_id):
                self.notification_state.mark_notified(tender, recipient_key=recipient_key)
                stats["notified"] += 1

        try:
            output_dir = Path(self.settings.config.get("export", {}).get("output_dir", "output"))
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            excel_path = output_dir / f"search_{search_number:03d}_{timestamp}.xlsx"
            export_path = export_tenders_to_excel(
                self.db,
                excel_path,
                tender_ids=export_tender_ids,
                search_number=search_number,
            )
            logger.info("Excel: создан новый файл текущего прогона: %s", export_path)
            self.email_notifier.send_excel(export_path, search_number)
        except Exception:
            logger.exception("Excel: ошибка экспорта результатов")
        return stats

    def run_cycle_for_user(self, user_id: str | int) -> list[dict[str, int]]:
        """Запустить все включённые профили пользователя и записать фактическую статистику."""
        user_id = str(user_id).strip()
        profiles = self.profile_store.list(user_id, enabled_only=True)
        if not profiles:
            profiles = [self.profile_store.ensure_default_profile(user_id, self.criteria_store)]
        results: list[dict[str, int]] = []
        aggregated_results: list[Tender] = []
        seen_keys: set[str] = set()
        for profile in profiles:
            if self.stop_requested:
                break
            started_at = datetime.now(timezone.utc).isoformat()
            stats = self.run_cycle(
                user_id=user_id,
                criteria=profile.criteria(),
                keywords=profile.keywords or None,
                platforms=profile.platforms or None,
                exclude_keywords=profile.exclusions,
                regions=profile.regions,
                notification_recipient_key=f"user:{user_id}",
                notification_chat_id=user_id,
            )
            self.profile_store.record_run(
                user_id,
                int(profile.id or 0),
                stats,
                started_at=started_at,
            )
            for tender in self.last_run_results:
                if tender.unique_key not in seen_keys:
                    seen_keys.add(tender.unique_key)
                    aggregated_results.append(tender)
            results.append(stats)
        self.last_run_results = aggregated_results
        return results
