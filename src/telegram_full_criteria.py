"""Telegram UI for the complete per-user tender criteria set."""
from __future__ import annotations

import html
import logging
import time

from src.crm.telegram import handle_callback as handle_crm_callback
from src.crm.telegram import handle_message as handle_crm_message
from src.telegram_criteria_multiuser import CriteriaAwareResponsiveTelegramBot

BTN_REGIONS = "Регионы"
BTN_EXCLUDE = "Исключить слова"
BTN_CRM = "CRM тендера"


class FullCriteriaTelegramBot(CriteriaAwareResponsiveTelegramBot):
    """Commercial criteria plus region/exclusion/CRM controls."""

    @staticmethod
    def _keyboard() -> dict:
        base = CriteriaAwareResponsiveTelegramBot._keyboard()
        keyboard = list(base["keyboard"])
        keyboard.insert(4, [{"text": BTN_REGIONS}, {"text": BTN_EXCLUDE}])
        keyboard.insert(5, [{"text": BTN_CRM}])
        base["keyboard"] = keyboard
        return base

    def _handle_message(self, message: dict) -> None:
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = (message.get("text") or "").strip()
        if not self._is_allowed(chat_id):
            self._access_denied(chat_id)
            return
        if self._is_owner(chat_id) and (
            chat_id in self._admin_waiting or text.startswith("/admin") or text.startswith("/users")
            or text.startswith("/add_user") or text.startswith("/remove_user")
        ):
            return super()._handle_message(message)
        if text == BTN_CRM:
            self._ask_value(chat_id, "crm_tender_id", "Введите внутренний ID тендера из базы.\n\nНапример:\n<code>123</code>")
            return
        if handle_crm_message(self, chat_id, text):
            return
        if text == BTN_REGIONS:
            self._ask_value(chat_id, "regions", "Введите регионы через запятую.\n\nНапример:\n<code>Санкт-Петербург, Ленинградская область, Москва</code>\n\n<code>нет</code> = все регионы.")
            return
        if text == BTN_EXCLUDE:
            self._ask_value(chat_id, "exclude_keywords", "Введите слова для исключения через запятую.\n\nНапример:\n<code>строительство, ремонт, продукты</code>\n\n<code>нет</code> = отключить пользовательские исключения.")
            return
        super()._handle_message(message)

    def _handle_callback(self, callback: dict) -> None:
        data = str(callback.get("data", ""))
        message = callback.get("message") or {}
        chat_id = str(message.get("chat", {}).get("id", ""))
        callback_id = str(callback.get("id", ""))
        if chat_id and self._is_allowed(chat_id) and handle_crm_callback(self, chat_id, data):
            self._answer_callback(callback_id)
            return
        super()._handle_callback(callback)

    def _handle_value_input(self, chat_id: str, text: str) -> bool:
        field = self._waiting_for.get(chat_id)
        if field == "crm_tender_id":
            self._waiting_for.pop(chat_id, None)
            if not text.strip().isdigit() or int(text.strip()) <= 0:
                self._send(chat_id, "ID тендера должен быть положительным целым числом.", self._keyboard())
                return True
            if handle_crm_message(self, chat_id, f"/tender {int(text.strip())}"):
                return True
            return True
        if field not in {"regions", "exclude_keywords"}:
            return super()._handle_value_input(chat_id, text)
        raw = text.strip()
        if ":" in raw:
            raw = raw.split(":", 1)[1].strip()
        values = [] if raw.casefold() in {"нет", "none", "off", "сброс", "сбросить"} else [x.strip() for x in raw.split(",") if x.strip()]
        if field == "regions":
            self.criteria_store.set_regions(chat_id, values)
            label = "Регионы"
        else:
            self.criteria_store.set_exclude_keywords(chat_id, values)
            label = "Исключающие слова"
        self._waiting_for.pop(chat_id, None)
        value_text = ", ".join(values) if values else "не задано"
        self._send(chat_id, f"<b>{label}:</b> {html.escape(value_text)}\n\nКритерий сохранён.", self._keyboard())
        return True

    def _cmd_settings(self, chat_id: str) -> None:
        super()._cmd_settings(chat_id)
        regions = self.criteria_store.get_regions(chat_id)
        exclusions = self.criteria_store.get_exclude_keywords(chat_id)
        text = (
            "<b>Дополнительные критерии</b>\n\n"
            f"Регионы: {html.escape(', '.join(regions) if regions else 'все')}\n"
            f"Исключающие слова: {html.escape(', '.join(exclusions) if exclusions else 'не заданы')}"
        )
        self._send(chat_id, text, self._keyboard())

    def _cmd_reset(self, chat_id: str) -> None:
        super()._cmd_reset(chat_id)
        self.criteria_store.set_regions(chat_id, [])
        self.criteria_store.set_exclude_keywords(chat_id, [])

    def _run_search_for_user(self, chat_id: str, orchestrator) -> None:
        started_at = time.monotonic()
        self._send(chat_id, "🔄 <b>Поиск выполняется...</b>\n\nИдёт сбор и анализ тендеров.", self._keyboard())
        try:
            criteria = self.criteria_store.get(chat_id)
            exclusions = self.criteria_store.get_exclude_keywords(chat_id) or None
            regions = self.criteria_store.get_regions(chat_id) or None
            stats = orchestrator.run_cycle(
                user_id=chat_id,
                criteria=criteria,
                exclude_keywords=exclusions,
                regions=regions,
            )
            self._send_search_results(chat_id, orchestrator)
            elapsed = int(time.monotonic() - started_at)
            elapsed_text = f"{elapsed // 60} мин. {elapsed % 60:02d} сек." if elapsed >= 60 else f"{elapsed} сек."
            state = "остановлен" if orchestrator.stop_requested else "завершён"
            text = (
                f"{'⛔' if orchestrator.stop_requested else '✅'} <b>Поиск №{stats['search_number']:03d} {state}.</b>\n\n"
                f"Время: {elapsed_text}\nНайдено: {stats['found']}\nПрошло фильтр: {stats['filtered']}\n"
                f"Новых: {stats['new']}\nAI: {stats['analyzed']}\nИсключено: {stats['excluded_by_criteria']}\n"
                f"Уведомлений: {stats['notified']}\nДублей: {stats['skipped_duplicate']}\n\n"
                "📊 <b>Результат сохранён в Excel.</b>"
            )
            self._send(chat_id, text, self._keyboard())
        except Exception:
            logging.getLogger(__name__).exception("Telegram-бот: ошибка выполнения расширенного поиска для chat_id=%s", chat_id)
            self._send(chat_id, "❌ <b>Ошибка поиска.</b>\n\nПодробности находятся в logs/agent.log.", self._keyboard())
        finally:
            with self._search_lock:
                self._search_threads.pop(chat_id, None)
                self._user_orchestrators.pop(chat_id, None)
