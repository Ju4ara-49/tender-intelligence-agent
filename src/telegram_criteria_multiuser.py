"""Extended Telegram UI exposing all tender commercial criteria."""
from __future__ import annotations

from src.telegram_bot import TelegramBot
from src.telegram_multiuser import (
    BTN_ADMIN,
    BTN_ADMIN_ADD,
    BTN_ADMIN_BACK,
    BTN_ADMIN_REMOVE,
    BTN_ADMIN_USERS,
)
from src.telegram_responsive import ResponsiveMultiUserTelegramBot


BTN_ADVANCE = "Аванс"
BTN_POSTPAYMENT = "Постоплата до:"
BTN_APP_SECURITY = "Обеспечение заявки до:"
BTN_CONTRACT_SECURITY = "Обеспечение контракта до:"


class CriteriaAwareResponsiveTelegramBot(ResponsiveMultiUserTelegramBot):
    """Responsive multi-user bot with the full TenderCriteria UI."""

    @staticmethod
    def _keyboard() -> dict:
        base = TelegramBot._keyboard()
        keyboard = list(base["keyboard"])
        keyboard.insert(2, [{"text": BTN_ADVANCE}, {"text": BTN_POSTPAYMENT}])
        keyboard.insert(3, [{"text": BTN_APP_SECURITY}, {"text": BTN_CONTRACT_SECURITY}])
        base["keyboard"] = keyboard
        return base

    def _handle_message(self, message: dict) -> None:
        text = (message.get("text") or "").strip()
        chat_id = str(message.get("chat", {}).get("id", ""))
        if not self._is_allowed(chat_id):
            self._access_denied(chat_id)
            return
        if self._is_owner(chat_id) and (
            chat_id in self._admin_waiting
            or text in {BTN_ADMIN_ADD, BTN_ADMIN_REMOVE, BTN_ADMIN_USERS, BTN_ADMIN_BACK, BTN_ADMIN}
            or text.startswith("/admin")
            or text.startswith("/users")
            or text.startswith("/add_user")
            or text.startswith("/remove_user")
        ):
            return super()._handle_message(message)
        if text == BTN_ADVANCE:
            self._ask_value(chat_id, "min_advance_percent", "Введите минимальный аванс в процентах.\n\n<code>30</code> = аванс от 30%.\n<code>0</code> = аванс не требуется.\n<code>нет</code> = отключить фильтр.")
            return
        if text == BTN_POSTPAYMENT:
            self._ask_value(chat_id, "max_postpayment_days", "Введите максимальную отсрочку платежа в днях.\n\nНапример: <code>30</code>.\n<code>нет</code> = отключить фильтр.")
            return
        if text == BTN_APP_SECURITY:
            self._ask_value(chat_id, "max_application_security_percent", "Введите максимальное обеспечение заявки в процентах.\n\nНапример: <code>5</code>.\n<code>нет</code> = отключить фильтр.")
            return
        if text == BTN_CONTRACT_SECURITY:
            self._ask_value(chat_id, "max_contract_security_percent", "Введите максимальное обеспечение контракта в процентах.\n\nНапример: <code>30</code>.\n<code>нет</code> = отключить фильтр.")
            return
        super()._handle_message(message)

    def _handle_value_input(self, chat_id: str, text: str) -> bool:
        field = self._waiting_for.get(chat_id)
        supported = {
            "min_advance_percent", "max_postpayment_days",
            "max_application_security_percent", "max_contract_security_percent",
        }
        if field not in supported:
            return super()._handle_value_input(chat_id, text)

        raw = text.strip()
        if ":" in raw:
            raw = raw.split(":", 1)[1].strip()
        if raw.casefold() in {"нет", "none", "off", "сброс", "сбросить"}:
            if field == "min_advance_percent":
                self.criteria_store.update(chat_id, min_advance_percent=0, advance_required=False)
            else:
                self.criteria_store.update(chat_id, **{field: None})
            self._waiting_for.pop(chat_id, None)
            self._send(chat_id, f"<b>{self._label(field)}:</b> фильтр отключён.", self._keyboard())
            return True

        try:
            value = float(raw.replace(" ", "").replace(",", ".")) if field != "max_postpayment_days" else int(raw)
            if value < 0 or (field != "max_postpayment_days" and value > 100):
                raise ValueError
        except ValueError:
            self._send(chat_id, "Некорректное значение. Введите число ещё раз.", self._keyboard())
            return True

        if field == "min_advance_percent":
            self.criteria_store.update(chat_id, min_advance_percent=value, advance_required=value > 0)
        else:
            self.criteria_store.update(chat_id, **{field: int(value) if field == "max_postpayment_days" else value})
        self._waiting_for.pop(chat_id, None)
        display = int(value) if float(value).is_integer() else value
        self._send(chat_id, f"<b>{self._label(field)}:</b> {display}\n\nКритерий сохранён.", self._keyboard())
        return True

    @staticmethod
    def _label(field: str) -> str:
        return {
            "min_advance_percent": "Аванс от",
            "max_postpayment_days": "Постоплата до",
            "max_application_security_percent": "Обеспечение заявки до",
            "max_contract_security_percent": "Обеспечение контракта до",
        }[field]

    def _cmd_settings(self, chat_id: str) -> None:
        criteria = self.criteria_store.get(chat_id)
        keywords = self.criteria_store.get_keywords(chat_id)
        platforms = self.criteria_store.get_enabled_platforms(chat_id)

        def fmt(value):
            if value is None:
                return "не задано"
            return f"{int(value)}" if float(value).is_integer() else f"{value:g}"

        keywords_text = ", ".join(keywords) if keywords else "из config/keywords.yaml"
        names = ", ".join(self._platform_name(p) for p in platforms)
        text = (
            "<b>Текущие критерии поиска</b>\n\n"
            f"Цена от: {fmt(criteria.min_price)}\n"
            f"Цена до: {fmt(criteria.max_price)}\n"
            f"Аванс от: {fmt(criteria.min_advance_percent)}% ({'требуется' if criteria.advance_required else 'не требуется'})\n"
            f"Постоплата до: {fmt(criteria.max_postpayment_days)} дн.\n"
            f"Обеспечение заявки до: {fmt(criteria.max_application_security_percent)}%\n"
            f"Обеспечение контракта до: {fmt(criteria.max_contract_security_percent)}%\n"
            f"Балл: {criteria.min_ai_score}\n"
            f"Срок: {criteria.min_submission_days} дн.\n"
            f"Ключевые слова: {keywords_text}\n"
            f"Площадки: {names}"
        )
        self._send(chat_id, text, self._keyboard())

    @staticmethod
    def _platform_name(platform: str) -> str:
        return {
            "eis": "ЕИС", "b2b_center": "B2B-Center", "rts_tender": "РТС-тендер",
            "fabrikant": "Фабрикант", "tmk": "ТМК", "rosatom": "Росатом",
        }.get(platform, platform)

    def _cmd_reset(self, chat_id: str) -> None:
        self.criteria_store.update(
            chat_id,
            min_price=None,
            max_price=None,
            advance_required=False,
            min_advance_percent=0,
            max_postpayment_days=None,
            min_submission_days=7,
            min_application_security_percent=0,
            max_application_security_percent=5,
            min_contract_security_percent=0,
            max_contract_security_percent=None,
            min_ai_score=70,
        )
        self.criteria_store.set_keywords(chat_id, [])
        self.criteria_store.set_enabled_platforms(chat_id, ["eis", "b2b_center", "fabrikant", "rts_tender", "tmk", "rosatom"])
        self._waiting_for.pop(chat_id, None)
        self._send(chat_id, "<b>Критерии поиска сброшены.</b>\n\nЦена: не задана\nАванс: не требуется\nПостоплата: не задана\nОбеспечение заявки: до 5%\nОбеспечение контракта: не задано\nБалл: 70\nСрок: 7 дн.", self._keyboard())
