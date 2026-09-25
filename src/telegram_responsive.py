"""Responsive Telegram polling runtime."""
from __future__ import annotations

import logging
import os
import time

import httpx

from src.security_redaction import redact_secrets
from src.telegram_bot import HELP_TEXT
from src.telegram_multiuser import MultiUserTelegramBot

logger = logging.getLogger(__name__)


class ResponsiveMultiUserTelegramBot(MultiUserTelegramBot):
    """Multi-user bot with interruptible short polling.

    Площадки и пользовательские критерии берутся из базового TelegramBot;
    этот класс отвечает только за сетевой polling и не делает monkey-patch
    глобальных словарей.
    """

    POLL_TIMEOUT_SECONDS = 2
    REQUEST_TIMEOUT_SECONDS = 15

    def run_polling(self) -> None:
        if not self.bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env — бот не может запуститься.")

        no_proxy_hosts = ["api.telegram.org"]
        existing = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
        hosts = [item.strip() for item in existing.split(",") if item.strip()]
        for host in no_proxy_hosts:
            if host not in hosts:
                hosts.append(host)
        no_proxy = ",".join(hosts)
        os.environ["NO_PROXY"] = no_proxy
        os.environ["no_proxy"] = no_proxy

        logger.info("Telegram-бот: api.telegram.org добавлен в NO_PROXY")
        logger.info("Telegram-бот запущен. Открытый доступ; admin_chat_id=%s", self.admin_chat_id or "не задан")
        if self.admin_chat_id:
            self._send(self.admin_chat_id, "Бот запущен. Пользовательский доступ открыт.\n\n" + HELP_TEXT, self._keyboard())
        while True:
            try:
                self._poll_once_responsive()
            except KeyboardInterrupt:
                logger.info("Telegram-бот остановлен (Ctrl+C)")
                break
            except httpx.ReadTimeout:
                logger.warning("Telegram-бот: timeout getUpdates; повторяем polling")
                time.sleep(1)
            except httpx.HTTPError as exc:
                logger.warning(
                    "Telegram-бот: временная HTTP-ошибка polling: %s",
                    redact_secrets(str(exc), (self.bot_token,) if self.bot_token else None),
                )
                time.sleep(2)
            except Exception:
                logger.exception("Telegram-бот: ошибка polling, продолжаем через 2 сек")
                time.sleep(2)

    def _poll_once_responsive(self) -> None:
        params = {"timeout": self.POLL_TIMEOUT_SECONDS, "allowed_updates": ["message", "callback_query"]}
        if self._offset is not None:
            params["offset"] = self._offset
        result = self._call("getUpdates", request_timeout=self.REQUEST_TIMEOUT_SECONDS, **params)
        for update in result.get("result", []):
            self._offset = update["update_id"] + 1
            if "callback_query" in update:
                logger.info("Telegram-бот: callback получен data=%s", update["callback_query"].get("data", ""))
                self._handle_callback(update["callback_query"])
            elif update.get("message"):
                self._handle_message(update["message"])
