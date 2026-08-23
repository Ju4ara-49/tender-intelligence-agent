"""Responsive Telegram polling runtime."""
from __future__ import annotations

import logging
import os
import time

import httpx

from src.telegram_bot import HELP_TEXT, PLATFORM_NAMES
from src.telegram_multiuser import MultiUserTelegramBot

logger = logging.getLogger(__name__)

PLATFORM_NAMES.clear()
PLATFORM_NAMES.update({
    "eis": "ЕИС",
    "b2b_center": "B2B-Center",
    "fabrikant": "Фабрикант",
    "rts_tender": "РТС-тендер",
    "tmk": "ТМК",
    "rosatom": "Росатом",
})


class ResponsiveMultiUserTelegramBot(MultiUserTelegramBot):
    """Multi-user bot with interruptible short polling."""

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
                # Long-polling timeout is a normal transient network event.
                # Do not emit a full traceback or make it look like the bot crashed.
                logger.warning("Telegram-бот: timeout getUpdates; повторяем polling")
                time.sleep(1)
            except httpx.HTTPError as exc:
                logger.warning("Telegram-бот: временная HTTP-ошибка polling: %s", exc)
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

    def _platform_keyboard(self, chat_id: str) -> dict:
        enabled = set(self._call_user(chat_id, self.criteria_store.get_enabled_platforms))
        rows = []
        for platform, name in PLATFORM_NAMES.items():
            mark = "☑" if platform in enabled else "☐"
            rows.append([{"text": f"{mark} {name}", "callback_data": f"platform:{platform}"}])
        rows.append([{"text": "Закрыть", "callback_data": "platform:close"}])
        return {"inline_keyboard": rows}

    def _show_platforms(self, chat_id: str) -> None:
        enabled = set(self._call_user(chat_id, self.criteria_store.get_enabled_platforms))
        lines = ["<b>Площадки поиска</b>", "", "Нажмите на площадку, чтобы включить или выключить её.", ""]
        for platform, name in PLATFORM_NAMES.items():
            lines.append(f"{'☑' if platform in enabled else '☐'} {name}")
        lines.append("")
        lines.append("<i>Подключены: ЕИС, B2B-Center, Фабрикант, РТС-тендер, ТМК и Росатом.</i>")
        self._send(chat_id, "\n".join(lines), self._platform_keyboard(chat_id))

    def _toggle_platform(self, chat_id: str, platform: str) -> None:
        if platform not in PLATFORM_NAMES:
            logger.warning("Telegram-бот: неизвестная площадка в callback: %s", platform)
            return
        current = set(self._call_user(chat_id, self.criteria_store.get_enabled_platforms))
        before = sorted(current)
        if platform in current:
            current.remove(platform)
        else:
            current.add(platform)
        self._call_user(chat_id, self.criteria_store.set_enabled_platforms, sorted(current))
        logger.info("Telegram-бот: площадка изменена chat_id=%s platform=%s before=%s after=%s", chat_id, platform, before, sorted(current))
        self._show_platforms(chat_id)
