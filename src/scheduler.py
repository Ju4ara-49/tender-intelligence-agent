"""Планировщик автоматических проверок."""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.orchestrator import Orchestrator
from src.settings import AppSettings

logger = logging.getLogger(__name__)


def _enabled_profile_users(orchestrator: Orchestrator) -> list[str]:
    """Return distinct users having at least one enabled saved search profile."""
    with orchestrator.db._connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM search_profiles "
            "WHERE enabled = 1 AND TRIM(user_id) <> '' ORDER BY user_id"
        ).fetchall()
    return [str(row["user_id"]).strip() for row in rows if str(row["user_id"]).strip()]


def run_scheduled(settings: AppSettings) -> None:
    """Запустить агент с периодическими проверками."""
    orchestrator = Orchestrator(settings)
    scheduler = BlockingScheduler(timezone=settings.config.get("app", {}).get("timezone", "Europe/Moscow"))

    interval = settings.scheduler_interval_minutes

    def job() -> None:
        logger.info("=== Запуск плановой проверки ===")
        try:
            users = _enabled_profile_users(orchestrator)
            if users:
                logger.info("Плановая проверка сохранённых профилей: пользователей=%d", len(users))
                for user_id in users:
                    if orchestrator.stop_requested:
                        break
                    try:
                        results = orchestrator.run_cycle_for_user(user_id)
                        logger.info("Пользователь %s: выполнено профилей=%d", user_id, len(results))
                    except Exception:
                        logger.exception("Ошибка плановой проверки пользователя %s", user_id)
            else:
                # Backward-compatible single-user/config mode when no Telegram
                # profiles exist in the database.
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
