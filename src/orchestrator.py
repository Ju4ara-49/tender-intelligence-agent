from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.ai.analyzer import TenderAnalyzer
from src.collectors.registry import get_enabled_collectors
from src.filters.keyword_filter import KeywordFilter
from src.models.tender import Tender
from src.notifications.telegram import TelegramNotifier
from src.notifications.email import EmailNotifier
from src.settings import AppSettings
from src.storage.database import TenderDatabase
from src.telegram_settings import CriteriaStore
from src.export.excel import export_tenders_to_excel

logger = logging.getLogger(__name__)


class Orchestrator:
    """Широкий multi-platform pipeline: discovery → dedup → enrich → filters → AI."""

    def _get_next_search_number(self) -> int:
        counter_path = Path(__file__).resolve().parent.parent / "data" / "search_counter.txt"
        counter_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            current = int(counter_path.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            current = 0
        next_number = current + 1
        counter_path.write_text(str(next_number), encoding="utf-8")
        return next_number

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.db = TenderDatabase(settings.database_path)
        self.criteria_store = CriteriaStore(self.db)
        self.analyzer = TenderAnalyzer(
            model=settings.ai_model,
            ai_context=settings.ai_context,
            use_stub_when_no_key=settings.ai_use_stub,
            ollama_url=settings.ollama_url,
        )
        logger.info(
            "AI: provider=%s | model=%s | ollama_url=%s | configured=%s",
            settings.ai_provider, settings.ai_model, settings.ollama_url,
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
            logger.info(
                "%s: загружаем детали тендера %s",
                getattr(collector, "platform", "unknown"), tender.external_id,
            )
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
            logger.info(
                "%s: детали загружены %s | price=%s | customer=%s | deadline=%s",
                getattr(collector, "platform", "unknown"), tender.external_id,
                tender.price, bool(tender.customer), tender.deadline,
            )
            return tender, loaded
        except Exception:
            logger.exception(
                "%s: ошибка загрузки деталей %s",
                getattr(collector, "platform", "unknown"), tender.external_id,
            )
            return self._normalize_tender_datetimes(tender), False

    def _search_platform(self, collector, keywords: list[str]) -> tuple[str, list[Tender]]:
        """Один сбой площадки не должен останавливать остальные."""
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
            key = tender.unique_key
            if key in seen:
                continue
            seen.add(key)
            result.append((collector, tender))
        return result

    def run_cycle(self) -> dict[str, int]:
        search_number = self._get_next_search_number()
        stats = {
            "search_number": search_number, "found": 0, "soft_filtered": 0,
            "filtered": 0, "keyword_excluded": 0, "new": 0, "analyzed": 0,
            "notified": 0, "skipped_duplicate": 0, "excluded_by_criteria": 0,
            "details_loaded": 0, "details_failed": 0,
        }
        self.clear_stop_request()
        self.last_run_results = []

        criteria = self.criteria_store.get()
        min_text = int(self.settings.config.get("filters", {}).get("min_text_length", 10))
        search_keywords = self.criteria_store.get_keywords() or self.settings.include_keywords
        enabled_platforms = self.criteria_store.get_enabled_platforms()
        logger.info("Поиск: используются ключевые слова: %s", search_keywords)
        logger.info("Поиск: включённые площадки из Telegram: %s", enabled_platforms)

        self.keyword_filter = KeywordFilter(
            include=search_keywords,
            exclude=self.settings.exclude_keywords,
            min_text_length=min_text,
        )
        collectors = get_enabled_collectors(self.settings.config, enabled_platforms=enabled_platforms)
        if not collectors:
            logger.warning("Нет включённых сборщиков. Проверьте config.yaml и настройки площадок.")
            return stats
        logger.info("Активные сборщики: %s", [c.platform for c in collectors])

        # 1. DISCOVERY — площадки работают независимо и параллельно.
        all_pairs: list[tuple[object, Tender]] = []
        workers = min(len(collectors), max(1, int(self.settings.config.get("search", {}).get("platform_workers", len(collectors)))))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="collector") as pool:
            futures = [pool.submit(self._search_platform, collector, search_keywords) for collector in collectors]
            for future in as_completed(futures):
                platform, found = future.result()
                collector = next((c for c in collectors if c.platform == platform), None)
                if collector is not None:
                    all_pairs.extend((collector, tender) for tender in found)
                    logger.info("Discovery: %s raw=%d", platform, len(found))

        stats["found"] = len(all_pairs)
        unique_pairs = self._deduplicate_pairs(all_pairs)
        logger.info("Discovery: total_raw=%d global_unique=%d duplicates=%d", len(all_pairs), len(unique_pairs), len(all_pairs) - len(unique_pairs))

        # 2. SOFT PRE-FILTER — только EXCLUDE/min_text/lookback.
        soft_pairs: list[tuple[object, Tender]] = []
        now = datetime.now(timezone.utc)
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
        logger.info("Soft pre-filter: %d/%d candidates remain", len(soft_pairs), len(unique_pairs))

        # 3. ENRICH — детали загружаются только после дешёвого soft-filter.
        enriched_pairs: list[tuple[object, Tender]] = []
        for collector, tender in soft_pairs:
            if self.stop_requested:
                break
            enriched, loaded = self._enrich_tender(collector, tender)
            if loaded:
                stats["details_loaded"] += 1
            elif callable(getattr(collector, "get_details", None)):
                stats["details_failed"] += 1
            enriched_pairs.append((collector, enriched))

        # 4. STRICT POST-FILTER — INCLUDE по полному тексту после enrichment.
        strict_pairs: list[tuple[object, Tender]] = []
        for collector, tender in enriched_pairs:
            if self.keyword_filter.matches_strict(tender):
                strict_pairs.append((collector, tender))
            else:
                stats["keyword_excluded"] += 1
        stats["filtered"] = len(strict_pairs)
        logger.info("Strict keyword filter: kept=%d excluded=%d", len(strict_pairs), stats["keyword_excluded"])

        # 5. USER CRITERIA + DB/notification dedup.
        current_run_tender_ids: list[int] = []
        for collector, tender in strict_pairs:
            if self.stop_requested:
                break

            if criteria.min_price is not None and tender.price is not None and tender.price < criteria.min_price:
                stats["excluded_by_criteria"] += 1
                continue
            if criteria.max_price is not None and tender.price is not None and tender.price > criteria.max_price:
                stats["excluded_by_criteria"] += 1
                continue
            if criteria.min_submission_days and tender.deadline is not None:
                days_left = (tender.deadline - datetime.now(timezone.utc)).days
                if days_left < criteria.min_submission_days:
                    stats["excluded_by_criteria"] += 1
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

        logger.info(
            "Цикл завершён: found=%d soft=%d filtered=%d kw_excluded=%d new=%d analyzed=%d notified=%d dup=%d excluded=%d details=%d failed=%d",
            stats["found"], stats["soft_filtered"], stats["filtered"], stats["keyword_excluded"],
            stats["new"], stats["analyzed"], stats["notified"], stats["skipped_duplicate"],
            stats["excluded_by_criteria"], stats["details_loaded"], stats["details_failed"],
        )

        try:
            output_dir = Path(self.settings.config.get("export", {}).get("output_dir", "output"))
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            excel_path = output_dir / f"search_{search_number:03d}_{timestamp}.xlsx"
            export_path = export_tenders_to_excel(
                self.db, excel_path, tender_ids=current_run_tender_ids, search_number=search_number
            )
            logger.info("Excel: создан новый файл текущего прогона: %s", export_path)
            self.email_notifier.send_excel(export_path, search_number)
        except Exception:
            logger.exception("Excel: ошибка экспорта результатов")
        return stats
