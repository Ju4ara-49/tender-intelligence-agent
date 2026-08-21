"""Планировщик автоматических проверок."""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.orchestrator import Orchestrator
from src.settings import AppSettings

logger = logging.getLogger(__name__)


def run_scheduled(settings: AppSettings) -> None:
    """Запустить агент с периодическими проверками."""
    orchestrator = Orchestrator(settings)
    scheduler = BlockingScheduler(timezone=settings.config.get("app", {}).get("timezone", "Europe/Moscow"))

    interval = settings.scheduler_interval_minutes

    def job() -> None:
        logger.info("=== Запуск плановой проверки ===")
        try:
            orchestrator.run_cycle()
        except Exception:
            logger.exception("Ошибка в цикле мониторинга")

    scheduler.add_job(
        job,
        trigger=IntervalTrigger(minutes=interval),
        id="tender_monitor",
        name="Tender Intelligence Monitor",
        replace_existing=True,
    )

    if settings.run_on_start:
        logger.info("Первый запуск сразу при старте")
        job()

    logger.info(
        "Планировщик запущен: проверка каждые %d мин. Нажмите Ctrl+C для остановки.",
        interval,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Планировщик остановлен")
