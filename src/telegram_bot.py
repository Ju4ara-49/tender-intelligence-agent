"""Интерактивный Telegram-бот Tender Intelligence Agent.

Доступ открыт для пользователей Telegram. Настройки и запущенные поиски
изолированы по chat_id пользователя. TELEGRAM_CHAT_ID используется только
для административного уведомления о запуске бота.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

from src.orchestrator import Orchestrator
from src.settings import AppSettings

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

BTN_PRICE_FROM = "Цена от:"
BTN_PRICE_TO = "Цена до:"
BTN_SCORE = "Балл:"
BTN_DAYS = "Срок:"
BTN_ADVANCE = "Аванс"
BTN_POSTPAYMENT = "Постоплата"
BTN_APP_SECURITY = "Обеспечение заявки"
BTN_CONTRACT_SECURITY = "Обеспечение контракта"
BTN_REGIONS = "Регионы"
BTN_KEYWORDS = "Ключевые слова"
BTN_EXCLUDE = "Исключающие слова"
BTN_PLATFORMS = "Площадки"
BTN_RESET = "Сброс"
BTN_SEARCH = "Поиск"
BTN_SETTINGS = "Настройки"
BTN_STOP = "Стоп"
BTN_HELP = "Помощь"

HELP_TEXT = (
    "<b>Добро пожаловать в Tender Intelligence Agent</b>\n\n"
    "Настройте параметры поиска кнопками ниже и нажмите «Поиск».\n\n"
    "<b>Команды</b>\n"
    "/start — открыть меню\n"
    "/search — запустить поиск\n"
    "/settings — показать критерии\n"
    "/стоп — остановить свой поиск\n"
    "/help — эта справка\n\n"
    "У каждого пользователя свои ключевые слова, фильтры и площадки."
)

PLATFORM_NAMES = {
    "eis": "ЕИС",
    "b2b_center": "B2B-Center",
    "rts_tender": "РТС-тендер",
    "fabrikant": "Фабрикант",
    "tmk": "ТМК",
    "rosatom": "Росатом",
}


class TelegramBot:
    """Long-polling Telegram-бот с многопользовательским режимом."""

    def __init__(self, settings: AppSettings, orchestrator: Orchestrator) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self.criteria_store = orchestrator.criteria_store
        self.bot_token = settings.telegram_bot_token
        self.admin_chat_id = str(settings.telegram_chat_id).strip()
        self._offset: int | None = None
        self._waiting_for: dict[str, str] = {}
        self._search_threads: dict[str, threading.Thread] = {}
        self._search_orchestrators: dict[str, Orchestrator] = {}

    def _call(self, method: str, request_timeout: float = 10.0, **params) -> dict:
        url = TELEGRAM_API.format(token=self.bot_token, method=method)
        timeout = httpx.Timeout(request_timeout, connect=5.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=params)
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise RuntimeError(f"Telegram API вернул некорректный JSON для {method}") from exc
            if not isinstance(data, dict) or data.get("ok") is not True:
                description = data.get("description") if isinstance(data, dict) else None
                error_code = data.get("error_code") if isinstance(data, dict) else None
                suffix = f" ({error_code})" if error_code is not None else ""
                raise RuntimeError(
                    f"Telegram API {method} завершился ошибкой{suffix}: {description or 'unknown error'}"
                )
            return data

    def _send(self, chat_id: str, text: str, reply_markup: dict | None = None) -> dict | None:
        try:
            params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
            if reply_markup is not None:
                params["reply_markup"] = reply_markup
            return self._call("sendMessage", request_timeout=10.0, **params)
        except (httpx.HTTPError, RuntimeError) as exc:
            logger.error("Telegram-бот: ошибка отправки chat_id=%s: %s", chat_id, exc)
            return None

    def _answer_callback(self, callback_query_id: str) -> None:
        try:
            self._call("answerCallbackQuery", request_timeout=10.0, callback_query_id=callback_query_id)
        except (httpx.HTTPError, RuntimeError) as exc:
            logger.error("Telegram-бот: ошибка callback: %s", exc)

    @staticmethod
    def _keyboard() -> dict:
        return {
            "keyboard": [
                [{"text": BTN_PRICE_FROM}, {"text": BTN_PRICE_TO}],
                [{"text": BTN_ADVANCE}, {"text": BTN_POSTPAYMENT}],
                [{"text": BTN_APP_SECURITY}, {"text": BTN_CONTRACT_SECURITY}],
                [{"text": BTN_DAYS}, {"text": BTN_SCORE}],
                [{"text": BTN_REGIONS}, {"text": BTN_EXCLUDE}],
                [{"text": BTN_KEYWORDS}, {"text": BTN_PLATFORMS}],
                [{"text": BTN_RESET}, {"text": BTN_SETTINGS}],
                [{"text": BTN_SEARCH}, {"text": BTN_STOP}],
                [{"text": BTN_HELP}],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def run_polling(self) -> None:
        if not self.bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env — бот не может запуститься.")
        logger.info("Telegram-бот запущен. Открытый доступ; admin_chat_id=%s", self.admin_chat_id or "не задан")
        if self.admin_chat_id:
            self._send(self.admin_chat_id, "Бот запущен. Пользовательский доступ открыт.\n\n" + HELP_TEXT, self._keyboard())
        while True:
            try:
                self._poll_once()
            except KeyboardInterrupt:
                logger.info("Telegram-бот остановлен (Ctrl+C)")
                break
            except Exception:
                logger.exception("Telegram-бот: ошибка polling, продолжаем через 5 сек")
                time.sleep(5)

    def _poll_once(self) -> None:
        params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
        if self._offset is not None:
            params["offset"] = self._offset
        result = self._call("getUpdates", request_timeout=35.0, **params)
        for update in result.get("result", []):
            self._offset = update["update_id"] + 1
            if "callback_query" in update:
                self._handle_callback(update["callback_query"])
            elif update.get("message"):
                self._handle_message(update["message"])

    def _handle_callback(self, callback: dict) -> None:
        callback_id = str(callback.get("id", ""))
        data = str(callback.get("data", ""))
        message = callback.get("message") or {}
        chat_id = str(message.get("chat", {}).get("id", ""))
        if not chat_id:
            self._answer_callback(callback_id)
            return
        try:
            if data == "platform:close":
                self._answer_callback(callback_id)
                self._send(chat_id, "Настройки площадок закрыты.", self._keyboard())
                return
            if data.startswith("platform:"):
                self._toggle_platform(chat_id, data.split(":", 1)[1])
            elif data == "keywords:clear":
                self.criteria_store.set_keywords(chat_id, [])
                self._answer_callback(callback_id)
                self._send(chat_id, "Ключевые слова очищены.", self._keyboard())
                return
            elif data == "keywords:edit":
                self._answer_callback(callback_id)
                self._ask_value(chat_id, "keywords", "Введите ключевые слова через запятую.\n\nНапример:\n<code>подшипники, муфты, запасные части</code>")
                return
            elif data == "exclude:clear":
                self.criteria_store.set_exclude_keywords(chat_id, [])
                self._answer_callback(callback_id)
                self._send(chat_id, "Исключающие слова очищены.", self._keyboard())
                return
            elif data == "exclude:edit":
                self._answer_callback(callback_id)
                self._ask_value(chat_id, "exclude_keywords", "Введите исключающие слова через запятую.\n\nНапример:\n<code>мебель, продукты питания</code>")
                return
            self._answer_callback(callback_id)
        except Exception:
            logger.exception("Telegram-бот: ошибка callback=%s", data)
            self._answer_callback(callback_id)

    def _platform_keyboard(self, chat_id: str) -> dict:
        enabled = set(self.criteria_store.get_enabled_platforms(chat_id))
        rows = []
        for platform, name in PLATFORM_NAMES.items():
            mark = "☑" if platform in enabled else "☐"
            rows.append([{"text": f"{mark} {name}", "callback_data": f"platform:{platform}"}])
        rows.append([{"text": "Закрыть", "callback_data": "platform:close"}])
        return {"inline_keyboard": rows}

    def _show_platforms(self, chat_id: str) -> None:
        enabled = set(self.criteria_store.get_enabled_platforms(chat_id))
        lines = ["<b>Площадки поиска</b>", "", "Нажмите на площадку, чтобы включить или выключить её.", ""]
        for platform, name in PLATFORM_NAMES.items():
            lines.append(f"{'☑' if platform in enabled else '☐'} {name}")
        lines += ["", "Поиск использует выбранные площадки. Если сборщик конкретной площадки временно недоступен, остальные площадки продолжают работать."]
        self._send(chat_id, "\n".join(lines), self._platform_keyboard(chat_id))

    def _toggle_platform(self, chat_id: str, platform: str) -> None:
        if platform not in PLATFORM_NAMES:
            return
        current = set(self.criteria_store.get_enabled_platforms(chat_id))
        if platform in current:
            current.remove(platform)
        else:
            current.add(platform)
        self.criteria_store.set_enabled_platforms(chat_id, list(current))
        self._show_platforms(chat_id)

    def _show_keywords(self, chat_id: str) -> None:
        keywords = self.criteria_store.get_keywords(chat_id)
        if keywords:
            text = "<b>Ключевые слова</b>\n\n" + "\n".join(f"{i}. {v}" for i, v in enumerate(keywords, 1))
        else:
            text = "<b>Ключевые слова</b>\n\nПользовательские ключевые слова не заданы.\n\nСейчас используются ключевые слова из config/keywords.yaml."
        keyboard = {"inline_keyboard": [[{"text": "Изменить", "callback_data": "keywords:edit"}], [{"text": "Очистить", "callback_data": "keywords:clear"}]]}
        self._send(chat_id, text, keyboard)

    def _show_exclude_keywords(self, chat_id: str) -> None:
        values = self.criteria_store.get_exclude_keywords(chat_id)
        text = "<b>Исключающие слова</b>\n\n" + ("\n".join(f"{i}. {v}" for i, v in enumerate(values, 1)) if values else "Не заданы.")
        keyboard = {"inline_keyboard": [[{"text": "Изменить", "callback_data": "exclude:edit"}], [{"text": "Очистить", "callback_data": "exclude:clear"}]]}
        self._send(chat_id, text, keyboard)

    def _handle_message(self, message: dict) -> None:
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            return
        logger.info("Telegram-бот: получено сообщение chat_id=%s: %s", chat_id, text)
        try:
            if chat_id in self._waiting_for:
                menu_buttons = {
                    BTN_PRICE_FROM, BTN_PRICE_TO, BTN_SCORE, BTN_DAYS, BTN_ADVANCE, BTN_POSTPAYMENT,
                    BTN_APP_SECURITY, BTN_CONTRACT_SECURITY, BTN_REGIONS, BTN_EXCLUDE, BTN_KEYWORDS,
                    BTN_PLATFORMS, BTN_RESET, BTN_SEARCH, BTN_SETTINGS, BTN_STOP, BTN_HELP,
                }
                if text not in menu_buttons and self._handle_value_input(chat_id, text):
                    return
                self._waiting_for.pop(chat_id, None)
            if text.startswith("/start") or text.startswith("/help") or text == BTN_HELP:
                self._cmd_help(chat_id)
            elif text.startswith("/settings") or text == BTN_SETTINGS:
                self._cmd_settings(chat_id)
            elif text.startswith("/search") or text.startswith("/run") or text == BTN_SEARCH:
                self._cmd_search(chat_id)
            elif text.startswith("/стоп") or text.startswith("/stop") or text == BTN_STOP:
                self._cmd_stop(chat_id)
            elif text == BTN_PRICE_FROM:
                self._ask_value(chat_id, "min_price", "Введите минимальную цену.\n\nНапример:\n<code>100000</code>")
            elif text == BTN_PRICE_TO:
                self._ask_value(chat_id, "max_price", "Введите максимальную цену.\n\nНапример:\n<code>5000000</code>")
            elif text == BTN_SCORE:
                self._ask_value(chat_id, "min_ai_score", "Введите минимальный балл AI от 0 до 100.\n\nНапример:\n<code>70</code>")
            elif text == BTN_DAYS:
                self._ask_value(chat_id, "min_submission_days", "Введите минимальное количество дней до дедлайна. По умолчанию 7.\n\nНапример:\n<code>7</code>")
            elif text == BTN_ADVANCE:
                self._ask_value(chat_id, "advance_required", "Нужен аванс? Введите <code>да</code> или <code>нет</code>.")
            elif text == BTN_POSTPAYMENT:
                self._ask_value(chat_id, "max_postpayment_days", "Введите максимальную отсрочку платежа в днях.\n\nНапример:\n<code>30</code>\n\nВведите 0, если постоплата не допускается.")
            elif text == BTN_APP_SECURITY:
                self._ask_value(chat_id, "max_application_security_percent", "Введите максимальное обеспечение заявки в процентах.\n\nНапример:\n<code>5</code>")
            elif text == BTN_CONTRACT_SECURITY:
                self._ask_value(chat_id, "max_contract_security_percent", "Введите максимальное обеспечение контракта в процентах.\n\nНапример:\n<code>30</code>")
            elif text == BTN_REGIONS:
                self._ask_value(chat_id, "regions", "Введите регионы через запятую.\n\nНапример:\n<code>Москва, Санкт-Петербург, Ленинградская область</code>")
            elif text == BTN_KEYWORDS:
                self._show_keywords(chat_id)
            elif text == BTN_EXCLUDE:
                self._show_exclude_keywords(chat_id)
            elif text == BTN_PLATFORMS:
                self._show_platforms(chat_id)
            elif text == BTN_RESET:
                self._cmd_reset(chat_id)
            else:
                self._send(chat_id, "Не понял команду.\n\nИспользуйте кнопки ниже или /help.", self._keyboard())
        except Exception:
            logger.exception("Telegram-бот: ошибка обработки chat_id=%s text=%s", chat_id, text)
            self._send(chat_id, "Что-то пошло не так при обработке команды.\nПодробности — в logs/agent.log.", self._keyboard())

    def _ask_value(self, chat_id: str, field: str, message: str) -> None:
        self._waiting_for[chat_id] = field
        self._send(chat_id, message, self._keyboard())

    def _handle_value_input(self, chat_id: str, text: str) -> bool:
        field = self._waiting_for.get(chat_id)
        if not field:
            return False
        if field in {"keywords", "exclude_keywords", "regions"}:
            values = [x.strip() for x in text.split(",") if x.strip()]
            if not values:
                self._send(chat_id, "Введите хотя бы одно значение через запятую.", self._keyboard())
                return True
            if field == "keywords":
                self.criteria_store.set_keywords(chat_id, values)
                label = "Ключевые слова"
            elif field == "exclude_keywords":
                self.criteria_store.set_exclude_keywords(chat_id, values)
                label = "Исключающие слова"
            else:
                self.criteria_store.set_regions(chat_id, values)
                label = "Регионы"
            self._waiting_for.pop(chat_id, None)
            self._send(chat_id, f"<b>{label} сохранены.</b>\n\n" + "\n".join(f"• {x}" for x in values), self._keyboard())
            return True
        if field == "advance_required":
            value = text.strip().casefold()
            if value in {"да", "д", "yes", "y", "1", "true"}:
                self.criteria_store.update(chat_id, advance_required=True)
                self._waiting_for.pop(chat_id, None)
                self._ask_value(chat_id, "min_advance_percent", "Введите минимальный размер аванса в процентах.\n\nНапример:\n<code>30</code>")
                return True
            if value in {"нет", "н", "no", "n", "0", "false"}:
                self.criteria_store.update(chat_id, advance_required=False, min_advance_percent=0.0)
                self._waiting_for.pop(chat_id, None)
                self._send(chat_id, "<b>Аванс:</b> не требуется.", self._keyboard())
                return True
            self._send(chat_id, "Введите «да» или «нет».", self._keyboard())
            return True
        raw = text.strip()
        if ":" in raw:
            raw = raw.split(":", 1)[1].strip()
        try:
            if field in {"min_price", "max_price", "min_advance_percent", "max_application_security_percent", "max_contract_security_percent"}:
                value = float(raw.replace(" ", "").replace(",", "."))
            else:
                value = int(raw)
            if value < 0:
                raise ValueError
        except ValueError:
            self._send(chat_id, "Некорректное значение. Введите неотрицательное число ещё раз.", self._keyboard())
            return True
        try:
            self.criteria_store.update(chat_id, **{field: value})
        except ValueError as exc:
            self._send(chat_id, f"Некорректный критерий: {exc}", self._keyboard())
            return True
        self._waiting_for.pop(chat_id, None)
        labels = {
            "min_price": "Цена от", "max_price": "Цена до", "min_ai_score": "Балл", "min_submission_days": "Срок",
            "min_advance_percent": "Минимальный аванс", "max_postpayment_days": "Максимальная постоплата",
            "max_application_security_percent": "Максимальное обеспечение заявки",
            "max_contract_security_percent": "Максимальное обеспечение контракта",
        }
        display = int(value) if isinstance(value, float) and value.is_integer() else value
        suffix = " %" if field in {"min_advance_percent", "max_application_security_percent", "max_contract_security_percent"} else (" дн." if field in {"min_submission_days", "max_postpayment_days"} else "")
        self._send(chat_id, f"<b>{labels.get(field, field)}:</b> {display}{suffix}\n\nКритерий сохранён.", self._keyboard())
        return True

    def _cmd_settings(self, chat_id: str) -> None:
        c = self.criteria_store.get(chat_id)
        keywords = self.criteria_store.get_keywords(chat_id)
        exclusions = self.criteria_store.get_exclude_keywords(chat_id)
        regions = self.criteria_store.get_regions(chat_id)
        platforms = self.criteria_store.get_enabled_platforms(chat_id)

        def fmt(v):
            if v is None:
                return "не задано"
            return f"{int(v):,}".replace(",", " ") if float(v).is_integer() else str(v)

        keywords_text = ", ".join(keywords) if keywords else "из config/keywords.yaml"
        exclusions_text = ", ".join(exclusions) if exclusions else "не заданы"
        regions_text = ", ".join(regions) if regions else "все регионы"
        names = ", ".join(PLATFORM_NAMES.get(p, p) for p in platforms) or "не выбраны"
        advance_text = "требуется" if c.advance_required else "не требуется"
        if c.advance_required and c.min_advance_percent:
            advance_text += f", от {fmt(c.min_advance_percent)}%"
        text = (
            "<b>Текущие критерии поиска</b>\n\n"
            f"Цена от: {fmt(c.min_price)}\nЦена до: {fmt(c.max_price)}\n"
            f"Аванс: {advance_text}\n"
            f"Постоплата до: {fmt(c.max_postpayment_days)} дн.\n"
            f"Обеспечение заявки до: {fmt(c.max_application_security_percent)}%\n"
            f"Обеспечение контракта до: {fmt(c.max_contract_security_percent)}%\n"
            f"Балл: {c.min_ai_score}\nСрок: {c.min_submission_days} дн.\n"
            f"Регионы: {regions_text}\n"
            f"Ключевые слова: {keywords_text}\n"
            f"Исключающие слова: {exclusions_text}\n"
            f"Площадки: {names}\n\n"
            "Измените нужный параметр кнопками ниже."
        )
        self._send(chat_id, text, self._keyboard())

    def _cmd_reset(self, chat_id: str) -> None:
        self.criteria_store.update(
            chat_id,
            min_price=None,
            max_price=None,
            advance_required=False,
            min_advance_percent=0.0,
            max_postpayment_days=None,
            min_ai_score=70,
            min_submission_days=7,
            min_application_security_percent=0.0,
            max_application_security_percent=5.0,
            min_contract_security_percent=0.0,
            max_contract_security_percent=None,
        )
        self.criteria_store.set_keywords(chat_id, [])
        self.criteria_store.set_exclude_keywords(chat_id, [])
        self.criteria_store.set_regions(chat_id, [])
        self.criteria_store.set_enabled_platforms(chat_id, list(PLATFORM_NAMES))
        self._waiting_for.pop(chat_id, None)
        self._send(chat_id, "<b>Критерии поиска сброшены.</b>\n\nЦена: без ограничения\nАванс: не требуется\nПостоплата: без ограничения\nОбеспечение заявки: до 5%\nБалл: 70\nСрок: 7 дн.\nРегионы: все\nКлючевые слова: из config/keywords.yaml\nИсключающие слова: не заданы\nПлощадки: все доступные", self._keyboard())

    def _cmd_search(self, chat_id: str) -> None:
        thread = self._search_threads.get(chat_id)
        if thread is not None and thread.is_alive():
            self._send(chat_id, "Ваш поиск уже выполняется.\n\nЕсли нужно остановить его — нажмите «Стоп».", self._keyboard())
            return
        self._send(chat_id, "Запускаю новый поиск тендеров.\n\nПоиск выполняется в фоне.", self._keyboard())
        search_orchestrator = Orchestrator(self.settings)
        search_orchestrator.notifier.chat_id = chat_id
        self._search_orchestrators[chat_id] = search_orchestrator
        thread = threading.Thread(target=self._run_search, args=(chat_id, search_orchestrator), daemon=True, name=f"telegram-search-{chat_id}")
        self._search_threads[chat_id] = thread
        thread.start()

    def _run_search(self, chat_id: str, search_orchestrator: Orchestrator) -> None:
        started_at = time.monotonic()
        self._send(chat_id, "🔄 <b>Поиск выполняется...</b>\n\nИдёт сбор и анализ тендеров.\n\n⏳ Пожалуйста, подождите...", self._keyboard())
        try:
            stats = search_orchestrator.run_cycle(user_id=chat_id)
            elapsed = int(time.monotonic() - started_at)
            elapsed_text = f"{elapsed // 60} мин. {elapsed % 60:02d} сек." if elapsed >= 60 else f"{elapsed} сек."
            state = "остановлен" if search_orchestrator.stop_requested else "завершён"
            text = (
                f"{'⛔' if search_orchestrator.stop_requested else '✅'} <b>Поиск №{stats['search_number']:03d} {state}.</b>\n\n"
                f"Время работы: {elapsed_text}\n\n"
                f"Найдено на площадках: {stats['found']}\n"
                f"Прошло фильтр по ключевым словам: {stats['filtered']}\n"
                f"Новых тендеров: {stats['new']}\n"
                f"Проанализировано AI: {stats['analyzed']}\n"
                f"Исключено по критериям: {stats['excluded_by_criteria']}\n"
                f"Отправлено уведомлений: {stats['notified']}\n"
                f"Пропущено дублей: {stats['skipped_duplicate']}\n\n"
                "📊 <b>Результат сохранён в Excel.</b>"
            )
            self._send(chat_id, text, self._keyboard())
        except Exception:
            logger.exception("Telegram-бот: ошибка выполнения поиска для chat_id=%s", chat_id)
            self._send(chat_id, "❌ <b>Ошибка поиска.</b>\n\nПодробности находятся в logs/agent.log.", self._keyboard())
        finally:
            self._search_threads.pop(chat_id, None)
            self._search_orchestrators.pop(chat_id, None)

    def _cmd_stop(self, chat_id: str) -> None:
        thread = self._search_threads.get(chat_id)
        search_orchestrator = self._search_orchestrators.get(chat_id)
        if thread is None or not thread.is_alive() or search_orchestrator is None:
            self._send(chat_id, "Сейчас ваш поиск не выполняется.", self._keyboard())
            return
        search_orchestrator.request_stop()
        self._send(chat_id, "Получена команда остановки вашего поиска. Текущий этап завершится, после чего поиск будет остановлен.", self._keyboard())

    def _cmd_help(self, chat_id: str) -> None:
        self._send(chat_id, HELP_TEXT, self._keyboard())

    def _cmd_status(self, chat_id: str) -> None:
        db = self.orchestrator.db
        text = (
            "<b>Статус агента</b>\n\n"
            f"Тендеров в базе: {db.count_tenders()}\n"
            f"Отправлено уведомлений всего: {db.count_notifications()}\n"
            f"AI: {self.settings.ai_model} ({self.settings.ai_provider})\n"
            f"Telegram: {'настроен' if self.settings.telegram_bot_token else 'dry-run'}"
        )
        self._send(chat_id, text, self._keyboard())