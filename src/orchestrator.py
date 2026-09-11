from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.ai.analyzer import TenderAnalyzer
from src.collectors.registry import get_enabled_collectors
from src.documents.tender_attachments import TenderAttachmentAnalyzer
from src.filters.keyword_filter import KeywordFilter
from src.models.tender import Tender
from src.notifications.telegram import TelegramNotifier
from src.notifications.email import EmailNotifier
from src.profiles import SearchProfileStore
from src.settings import AppSettings
from src.storage.database import TenderDatabase
from src.telegram_settings import CriteriaStore, TenderCriteria
from src.export.excel import export_tenders_to_excel

logger = logging.getLogger(__name__)


class Orchestrator:
    """Широкий multi-platform pipeline: discovery → dedup → enrich → documents → filters → AI."""

    def _get_next_search_number(self) -> int:
        return self.db.next_search_number()

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.db = TenderDatabase(settings.database_path)
        self.criteria_store = CriteriaStore(self.db)
        self.profile_store = SearchProfileStore(self.db)
        self.document_analyzer = TenderAttachmentAnalyzer(
            max_attachments=int(settings.config.get("documents", {}).get("max_attachments", 30)),
        )
        self.analyzer = TenderAnalyzer(
            model=settings.ai_model,
            ai_context=settings.ai_context,
            use_stub_when_no_key=settings.ai_use_stub,
            ollama_url=settings.ollama_url,
        )
        logger.info(
            "AI: provider=%s | model=%s | ollama_url=%s | configured=%s",
            settings.ai_provider, settings.ai_model, settings.ollama_url, self.analyzer.is_configured,
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
        tender.deadline = self._normalize_datetime(tender.deadline)
        tender.published_at = self._normalize_datetime(tender.published_at)
        return tender

    def _enrich_tender(self, collector, tender: Tender) -> tuple[Tender, bool]:
        get_details = getattr(collector, "get_details", None)
        if not callable(get_details) or not tender.external_id:
            return self._normalize_tender_datetimes(tender), False
        try:
            logger.info("%s: загружаем детали тендера %s", getattr(collector, "platform", "unknown"), tender.external_id)
            detailed = get_details(tender.external_id)
            if detailed:
                if detailed.title:
                    tender.title = detailed.title
                if detailed.description:
                    tender.description = detailed.description
                if detailed.price is not None:
                    tender.price = detailed.price
                if detailed.currency:
                    tender.currency = detailed.currency
                if tender.deadline is None and detailed.deadline:
                    tender.deadline = detailed.deadline
                if tender.published_at is None and detailed.published_at:
                    tender.published_at = detailed.published_at
                if not tender.region and detailed.region:
                    tender.region = detailed.region
                if not tender.customer and detailed.customer:
                    tender.customer = detailed.customer
                if detailed.law_type:
                    tender.law_type = detailed.law_type
                if detailed.url:
                    tender.url = detailed.url
                if detailed.raw_data:
                    for key in (
                        "procurement_method", "application_security", "contract_security",
                        "advance_payment", "postpayment", "lots", "lot", "specification",
                        "specifications", "items", "products",
                    ):
                        if detailed.raw_data.get(key):
                            tender.raw_data[key] = detailed.raw_data[key]
                    tender.raw_data["details"] = detailed.raw_data
                tender.raw_data["details_loaded"] = True
            tender = self._normalize_tender_datetimes(tender)
            loaded = bool(tender.raw_data.get("details_loaded"))
            logger.info("%s: детали загружены %s | price=%s | customer=%s | deadline=%s", getattr(collector, "platform", "unknown"), tender.external_id, tender.price, bool(tender.customer), tender.deadline)
            return tender, loaded
        except Exception:
            logger.exception("%s: ошибка загрузки деталей %s", getattr(collector, "platform", "unknown"), tender.external_id)
            return self._normalize_tender_datetimes(tender), False

    def _analyze_tender_documents(self, tender: Tender, keywords: list[str]) -> bool:
        """Скачать и проиндексировать вложения тендера локально.

        Ошибка одного документа не ломает весь поиск. Результаты сохраняются
        в raw_data и автоматически попадают в Tender.full_text.
        """
        if not tender.raw_data or not keywords:
            return False
        try:
            attachments = self.document_analyzer.discover(tender.raw_data)
            if not attachments:
                return False
            analyses = self.document_analyzer.analyze(tender.raw_data, keywords)
            document_search: list[dict[str, object]] = []
            for item in analyses:
                for document in item.documents:
                    document_search.append({
                        "filename": document.path,
                        "text": document.text,
                    })
                for hit in item.hits:
                    document_search.append({
                        "filename": hit.path,
                        "keyword": hit.keyword,
                        "snippet": hit.snippet,
                        "start": hit.start,
                        "end": hit.end,
                    })
            tender.raw_data["document_search"] = document_search
            tender.raw_data["document_search_attachments"] = len(analyses)
            tender.raw_data["document_search_hits"] = sum(len(item.hits) for item in analyses)
            logger.info(
                "%s:%s: документы проанализированы | attachments=%d | hits=%d",
                tender.platform,
                tender.external_id,
                len(analyses),
                tender.raw_data["document_search_hits"],
            )
            return bool(document_search)
        except Exception:
            logger.exception("%s:%s: ошибка анализа вложений; продолжаем без документов", tender.platform, tender.external_id)
            return False

    def _search_platform(self, collector, keywords: list[str]) -> tuple[str, list[Tender]]:
        platform = getattr(collector, "platform", "unknown")
        try:
            config = self.settings.config.get("collectors", {}).get(platform, {})
            lookback_days = int(config.get("lookback_days", 3))
            since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            found = collector.search(keywords=keywords, since=since) or []
            logger.info("Discovery: platform=%s keywords=%d raw=%d", platform, len(keywords), len(found))
            return platform, list(found)
        except Exception:
            logger.exception("Discovery: площадка %s завершилась ошибкой; продолжаем поиск", platform)
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
        if criteria.min_advance_percent > 0 and (tender.advance_percent is None or tender.advance_percent < criteria.min_advance_percent):
            return False, "min_advance_percent"
        if criteria.max_postpayment_days is not None and (tender.postpayment_days or 0) > criteria.max_postpayment_days:
            return False, "max_postpayment_days"
        if criteria.min_application_security_percent > 0 and (
            tender.application_security_percent is None or tender.application_security_percent < criteria.min_application_security_percent
        ):
            return False, "min_application_security_percent"
        if criteria.max_application_security_percent is not None and (tender.application_security_percent or 0.0) > criteria.max_application_security_percent:
            return False, "max_application_security_percent"
        if criteria.min_contract_security_percent > 0 and (
            tender.contract_security_percent is None or tender.contract_security_percent < criteria.min_contract_security_percent
        ):
            return False, "min_contract_security_percent"
        if criteria.max_contract_security_percent is not None and (tender.contract_security_percent or 0.0) > criteria.max_contract_security_percent:
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
    ) -> dict[str, int]:
        search_number = self._get_next_search_number()
        stats = {
            "search_number": search_number, "found": 0, "soft_filtered": 0, "filtered": 0,
            "keyword_excluded": 0, "new": 0, "analyzed": 0, "notified": 0,
            "skipped_duplicate": 0, "excluded_by_criteria": 0, "excluded_by_region": 0,
            "details_loaded": 0, "details_failed": 0, "document_hits": 0,
        }
        self.clear_stop_request()
        self.last_run_results = []

        criteria = criteria if criteria is not None else self.criteria_store.get(user_id)
        min_text = int(self.settings.config.get("filters", {}).get("min_text_length", 10))
        search_keywords = keywords if keywords is not None else (self.criteria_store.get_keywords(user_id) or self.settings.include_keywords)
        enabled_platforms = platforms if platforms is not None else self.criteria_store.get_enabled_platforms(user_id)
        exclusions = exclude_keywords if exclude_keywords is not None else self.settings.exclude_keywords
        logger.info("Поиск: user_id=%s | keywords=%s | platforms=%s | regions=%s", user_id, search_keywords, enabled_platforms, regions or [])

        self.keyword_filter = KeywordFilter(include=search_keywords, exclude=exclusions, min_text_length=min_text)
        collectors = get_enabled_collectors(self.settings.config, enabled_platforms=enabled_platforms)
        if not collectors:
            logger.warning("Нет включённых сборщиков. Проверьте config.yaml и настройки площадок.")
            return stats

        all_pairs: list[tuple[object, Tender]] = []
        workers = min(len(collectors), max(1, int(self.settings.config.get("search", {}).get("platform_workers", len(collectors)))))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="collector") as pool:
            futures = [pool.submit(self._search_platform, collector, search_keywords) for collector in collectors]
            for future in as_completed(futures):
                platform, found = future.result()
                collector = next((c for c in collectors if c.platform == platform), None)
                if collector is not None:
                    all_pairs.extend((collector, tender) for tender in found)

        stats["found"] = len(all_pairs)
        unique_pairs = self._deduplicate_pairs(all_pairs)
        now = datetime.now(timezone.utc)
        soft_pairs: list[tuple[object, Tender]] = []
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

        enriched_pairs: list[tuple[object, Tender]] = []
        for collector, tender in soft_pairs:
            if self.stop_requested:
                break
            enriched, loaded = self._enrich_tender(collector, tender)
            stats["details_loaded"] += int(loaded)
            stats["details_failed"] += int(not loaded and callable(getattr(collector, "get_details", None)))
            if self._analyze_tender_documents(enriched, search_keywords):
                stats["document_hits"] += int(enriched.raw_data.get("document_search_hits", 0))
            enriched_pairs.append((collector, enriched))

        strict_pairs: list[tuple[object, Tender]] = []
        for collector, tender in enriched_pairs:
            if self.keyword_filter.matches_strict(tender):
                strict_pairs.append((collector, tender))
            else:
                stats["keyword_excluded"] += 1
        stats["filtered"] = len(strict_pairs)

        current_run_tender_ids: list[int] = []
        for collector, tender in strict_pairs:
            if self.stop_requested:
                break
            if not self._passes_regions(tender, regions):
                stats["excluded_by_region"] += 1
                continue
            passed, reason = self._passes_criteria(tender, criteria)
            if not passed:
                stats["excluded_by_criteria"] += 1
                logger.debug("Критерии: исключён %s:%s (%s)", tender.platform, tender.external_id, reason)
                continue
            self.last_run_results.append(tender)
            existing = self.db.exists(tender.unique_key)
            tender_id = self.db.save_tender(tender)
            current_run_tender_ids.append(tender_id)
            if existing and self.db.was_notified(tender.unique_key):
                stats["skipped_duplicate"] += 1
                continue
            if not existing:
                stats["new"] += 1
            analysis = self.analyzer.analyze(tender)
            self.db.save_analysis(tender_id, analysis)
            stats["analyzed"] += 1
            if analysis.relevance_score < criteria.min_ai_score:
                continue
            if self.db.was_notified(tender.unique_key):
                stats["skipped_duplicate"] += 1
                continue
            if self.notifier.send_tender_alert(tender, analysis):
                self.db.mark_notified(tender_id)
                stats["notified"] += 1

        try:
            output_dir = Path(self.settings.config.get("export", {}).get("output_dir", "output"))
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            excel_path = output_dir / f"search_{search_number:03d}_{timestamp}.xlsx"
            export_path = export_tenders_to_excel(self.db, excel_path, tender_ids=current_run_tender_ids, search_number=search_number)
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
        aggregate_results: list[Tender] = []
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
                exclude_keywords=profile.exclusions or None,
                regions=profile.regions or None,
            )
            for tender in self.last_run_results:
                if tender.unique_key not in seen_keys:
                    seen_keys.add(tender.unique_key)
                    aggregate_results.append(tender)
            self.profile_store.record_run(user_id, profile.id, stats, started_at=started_at)
            results.append(stats)
        self.last_run_results = aggregate_results
        return results
