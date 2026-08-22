from __future__ import annotations

import logging
import threading
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
    def _get_next_search_number(self) -> int:
        """Возвращает следующий постоянный номер поиска."""
        counter_path = Path(__file__).resolve().parent.parent / "data" / "search_counter.txt"
        counter_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            current = int(counter_path.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            current = 0
        next_number = current + 1
        counter_path.write_text(str(next_number), encoding="utf-8")
        return next_number

    """Сбор → детализация → фильтр → AI → уведомление → БД."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.db = TenderDatabase(settings.database_path)
        self.criteria_store = CriteriaStore(self.db)
        min_text = int(settings.config.get("filters", {}).get("min_text_length", 10))
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

    def _enrich_tender(self, collector, tender: Tender) -> Tender:
        get_details = getattr(collector, "get_details", None)
        if not callable(get_details):
            logger.debug("Коллектор %s не поддерживает get_details()", getattr(collector, "platform", "unknown"))
            return tender
        if not tender.external_id:
            logger.warning("Невозможно загрузить детали: отсутствует external_id")
            return tender
        try:
            logger.info("%s: загружаем детали тендера %s", getattr(collector, "platform", "unknown"), tender.external_id)
            detailed = get_details(tender.external_id)
            if detailed is None:
                logger.warning("%s: детали не получены для %s", getattr(collector, "platform", "unknown"), tender.external_id)
                return tender
            if detailed.title: tender.title = detailed.title
            if detailed.description: tender.description = detailed.description
            if detailed.price is not None: tender.price = detailed.price
            if detailed.deadline is not None: tender.deadline = detailed.deadline
            if detailed.published_at is not None: tender.published_at = detailed.published_at
            if detailed.region: tender.region = detailed.region
            if detailed.customer: tender.customer = detailed.customer
            if detailed.law_type: tender.law_type = detailed.law_type
            if not isinstance(tender.raw_data, dict): tender.raw_data = {}
            tender.raw_data["details_loaded"] = True
            if isinstance(detailed.raw_data, dict):
                for key in ("procurement_method", "status"):
                    value = detailed.raw_data.get(key)
                    if value: tender.raw_data[key] = value
                tender.raw_data["details"] = detailed.raw_data
            logger.info(
                "%s: детали загружены %s | price=%s | customer=%s | deadline=%s",
                getattr(collector, "platform", "unknown"), tender.external_id, tender.price, bool(tender.customer), tender.deadline,
            )
            return tender
        except Exception:
            logger.exception("%s: ошибка загрузки деталей %s", getattr(collector, "platform", "unknown"), tender.external_id)
            return tender

    def run_cycle(self) -> dict[str, int]:
        search_number = self._get_next_search_number()
        stats = {
            "search_number": search_number, "found": 0, "filtered": 0, "new": 0,
            "analyzed": 0, "notified": 0, "skipped_duplicate": 0,
            "excluded_by_criteria": 0, "details_loaded": 0, "details_failed": 0,
        }
        self.clear_stop_request()
        self.last_run_results = []
        criteria = self.criteria_store.get()
        min_text = int(self.settings.config.get("filters", {}).get("min_text_length", 10))
        telegram_keywords = self.criteria_store.get_keywords()
        search_keywords = telegram_keywords if telegram_keywords else self.settings.include_keywords
        logger.info("Поиск: используются ключевые слова: %s", search_keywords)
        self.keyword_filter = KeywordFilter(include=search_keywords, exclude=self.settings.exclude_keywords, min_text_length=min_text)
        enabled_platforms = self.criteria_store.get_enabled_platforms()
        logger.info("Поиск: включённые площадки из Telegram: %s", enabled_platforms)
        collectors = get_enabled_collectors(self.settings.config, enabled_platforms=enabled_platforms)
        if not collectors:
            logger.warning("Нет включённых сборщиков. Проверьте config.yaml и настройки площадок.")
            return stats
        logger.info("Активные сборщики: %s", [collector.platform for collector in collectors])
        all_tenders: list[tuple[object, Tender]] = []
        current_run_tender_ids: list[int] = []
        for collector in collectors:
            if self.stop_requested: break
            logger.info("Запуск сборщика: %s", collector.platform)
            collector_config = self.settings.config.get("collectors", {}).get(collector.platform, {})
            since = datetime.now(timezone.utc) - timedelta(days=int(collector_config.get("lookback_days", 3)))
            found = collector.search(keywords=search_keywords, since=since)
            all_tenders.extend((collector, tender) for tender in found)
        stats["found"] = len(all_tenders)
        logger.info("Всего найдено тендеров: %d", stats["found"])

        for collector, tender in all_tenders:
            if self.stop_requested: break
            if not self.keyword_filter.matches(tender): continue
            stats["filtered"] += 1
            if self.db.exists(tender.unique_key):
                existing_tender_id = self.db.get_tender_id(tender.unique_key)
                if existing_tender_id is not None: current_run_tender_ids.append(existing_tender_id)
                if self.db.was_notified(tender.unique_key):
                    stats["skipped_duplicate"] += 1
                    continue
            before_details = bool(tender.deadline) and bool(tender.customer)
            tender = self._enrich_tender(collector, tender)
            details_loaded = isinstance(tender.raw_data, dict) and tender.raw_data.get("details_loaded") is True
            if details_loaded: stats["details_loaded"] += 1
            elif not before_details: stats["details_failed"] += 1
            if criteria.min_price is not None and tender.price is not None and tender.price < criteria.min_price:
                stats["excluded_by_criteria"] += 1; continue
            if criteria.max_price is not None and tender.price is not None and tender.price > criteria.max_price:
                stats["excluded_by_criteria"] += 1; continue
            if criteria.min_submission_days and tender.deadline is not None:
                days_left = (tender.deadline - datetime.now(timezone.utc)).days
                if days_left < criteria.min_submission_days:
                    stats["excluded_by_criteria"] += 1; continue
            self.last_run_results.append(tender)
            tender_id = self.db.save_tender(tender)
            stats["new"] += 1
            current_run_tender_ids.append(tender_id)
            analysis = self.analyzer.analyze(tender)
            self.db.save_analysis(tender_id, analysis)
            stats["analyzed"] += 1
            if analysis.relevance_score < criteria.min_ai_score: continue
            if self.db.was_notified(tender.unique_key):
                stats["skipped_duplicate"] += 1
                continue
            sent = self.notifier.send_tender_alert(tender, analysis)
            if sent:
                self.db.mark_notified(tender_id); stats["notified"] += 1

        logger.info(
            "Цикл завершён: found=%d filtered=%d new=%d analyzed=%d notified=%d dup=%d excluded=%d details=%d failed=%d",
            stats["found"], stats["filtered"], stats["new"], stats["analyzed"], stats["notified"],
            stats["skipped_duplicate"], stats["excluded_by_criteria"], stats["details_loaded"], stats["details_failed"],
        )
        try:
            export_config = self.settings.config.get("export", {})
            output_dir = Path(export_config.get("output_dir", "output")); output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            excel_path = output_dir / f"search_{search_number:03d}_{timestamp}.xlsx"
            export_path = export_tenders_to_excel(self.db, excel_path, tender_ids=current_run_tender_ids, search_number=search_number)
            logger.info("Excel: создан новый файл текущего прогона: %s", export_path)
            self.email_notifier.send_excel(export_path, search_number)
        except Exception:
            logger.exception("Excel: ошибка экспорта результатов")
        return stats
