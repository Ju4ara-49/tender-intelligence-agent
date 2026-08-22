"""Responsive Telegram polling runtime.

Keeps getUpdates requests short so Ctrl+C is handled promptly instead of
waiting for Telegram's long-poll timeout.
"""
from __future__ import annotations

import logging
import time

from src.telegram_multiuser import MultiUserTelegramBot

logger = logging.getLogger(__name__)


class ResponsiveMultiUserTelegramBot(MultiUserTelegramBot):
    """Multi-user bot with interruptible short polling."""

    POLL_TIMEOUT_SECONDS = 2
    REQUEST_TIMEOUT_SECONDS = 6

    def run_polling(self) -> None:
        if not self.bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env — бот не может запуститься.")
        logger.info(
            "Telegram-бот запущен. Открытый доступ; admin_chat_id=%s",
            self.admin_chat_id or "не задан",
        )
        if self.admin_chat_id:
            self._send(
                self.admin_chat_id,
                "Бот запущен. Пользовательский доступ открыт.\n\n" + self.HELP_TEXT
                if hasattr(self, "HELP_TEXT")
                else "Бот запущен. Пользовательский доступ открыт.",
                self._keyboard(),
            )
        while True:
            try:
                self._poll_once_responsive()
            except KeyboardInterrupt:
                logger.info("Telegram-бот остановлен (Ctrl+C)")
                break
            except Exception:
                logger.exception("Telegram-бот: ошибка polling, продолжаем через 2 сек")
                time.sleep(2)

    def _poll_once_responsive(self) -> None:
        params = {
            "timeout": self.POLL_TIMEOUT_SECONDS,
            "allowed_updates": ["message", "callback_query"],
        }
        if self._offset is not None:
            params["offset"] = self._offset
        result = self._call(
            "getUpdates",
            request_timeout=self.REQUEST_TIMEOUT_SECONDS,
            **params,
        )
        for update in result.get("result", []):
            self._offset = update["update_id"] + 1
            if "callback_query" in update:
                self._handle_callback(update["callback_query"])
            elif update.get("message"):
                self._handle_message(update["message"])
