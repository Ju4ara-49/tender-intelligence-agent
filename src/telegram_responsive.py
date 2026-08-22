"""Responsive Telegram polling runtime."""
from __future__ import annotations

import logging
import os
import time

from src.telegram_bot import HELP_TEXT, PLATFORM_NAMES
from src.telegram_multiuser import MultiUserTelegramBot

logger = logging.getLogger(__name__)


class ResponsiveMultiUserTelegramBot(MultiUserTelegramBot):
    """Multi-user bot with interruptible short polling."""

    POLL_TIMEOUT_SECONDS = 2
    REQUEST_TIMEOUT_SECONDS = 6

    def run_polling(self) -> None:
        if not self.bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env — бот не может запуститься.")

        # Telegram API must bypass any system/WinINET proxy configuration.
        # httpx uses trust_env=True by default, and on some Windows setups
        # this can result in TLS EOF errors while connecting to api.telegram.org.
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
                self._handle_callback(update["callback_query"])
            elif update.get("message"):
                self._handle_message(update["message"])

    def _show_platforms(self, chat_id: str) -> None:
        enabled = set(self._call_user(chat_id, self.criteria_store.get_enabled_platforms))
        lines = ["<b>Площадки поиска</b>", "", "Нажмите на площадку, чтобы включить или выключить её.", ""]
        for platform, name in PLATFORM_NAMES.items():
            lines.append(f"{'☑' if platform in enabled else '☐'} {name}")
        lines += ["", "<i>Подключены: ЕИС, B2B-Center, UniPro, РТС-тендер и ТМК.</i>", "<i>B2B-Center использует сохранённую авторизованную сессию.</i>"]
        self._send(chat_id, "\n".join(lines), self._platform_keyboard(chat_id))
