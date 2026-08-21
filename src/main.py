"""Точка входа Tender Intelligence Agent."""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler

from src.orchestrator import Orchestrator
from src.scheduler import run_scheduled
from src.settings import PROJECT_ROOT, load_settings


def setup_logging(settings) -> None:
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    log_file = settings.log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)

    max_bytes = int(settings.config.get("logging", {}).get("max_bytes", 5_242_880))
    backup_count = int(settings.config.get("logging", {}).get("backup_count", 3))

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        ),
    ]

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tender Intelligence Agent — мониторинг тендеров",
    )
    parser.add_argument(
        "command",
        choices=["run", "once", "status", "bot"],
        help=(
            "run — непрерывный режим; once — одна проверка; "
            "status — статистика БД; "
            "bot — интерактивный Telegram-бот (/settings, /search)"
        ),
    )
    args = parser.parse_args()

    settings = load_settings()
    setup_logging(settings)

    logger = logging.getLogger(__name__)
    logger.info("Tender Intelligence Agent v0.1.0")
    logger.info("Рабочая папка: %s", PROJECT_ROOT)

    if args.command == "status":
        from src.storage.database import TenderDatabase

        db = TenderDatabase(settings.database_path)

        print(f"Тендеров в базе:      {db.count_tenders()}")
        print(f"Отправлено уведомлений: {db.count_notifications()}")
        print(
            f"Telegram настроен:    "
            f"{'да' if settings.telegram_bot_token else 'нет (dry-run)'}"
        )

        if settings.ai_provider.lower() == "ollama":
            print(
                f"ИИ настроен:          "
                f"{'да' if settings.ollama_url else 'нет'} "
                f"(Ollama / {settings.ai_model})"
            )
        else:
            print(
                f"ИИ настроен:          "
                f"{'да' if settings.ai_api_key else 'нет'} "
                f"({settings.ai_provider} / {settings.ai_model})"
            )

        return 0

    if args.command == "once":
        orchestrator = Orchestrator(settings)
        stats = orchestrator.run_cycle()
        print("Результат проверки:", stats)
        return 0

    if args.command == "run":
        run_scheduled(settings)
        return 0

    if args.command == "bot":
        from src.telegram_bot import TelegramBot

        orchestrator = Orchestrator(settings)
        bot = TelegramBot(settings, orchestrator)
        bot.run_polling()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
