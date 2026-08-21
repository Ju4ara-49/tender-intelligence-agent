"""
Интерактивный Telegram-бот Tender Intelligence Agent.

Интерфейс:
    Цена от:
    Цена до:
    Балл:
    Срок:
    Ключевые слова
    Площадки
    Сброс
    Поиск
    Настройки
    Стоп
    Помощь

Площадки переключаются интерактивными кнопками.
Ключевые слова хранятся в SQLite через CriteriaStore.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx

from src.orchestrator import Orchestrator
from src.settings import AppSettings

logger = logging.getLogger(__name__)

# ?? ???????? ??? ??????????? HTTP-????????? long polling Telegram.
logging.getLogger("httpx").setLevel(logging.WARNING)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


# ==========================================================
# КНОПКИ
# ==========================================================

BTN_PRICE_FROM = "Цена от:"
BTN_PRICE_TO = "Цена до:"
BTN_SCORE = "Балл:"
BTN_DAYS = "Срок:"

BTN_KEYWORDS = "Ключевые слова"
BTN_PLATFORMS = "Площадки"

BTN_RESET = "Сброс"

BTN_SEARCH = "Поиск"
BTN_SETTINGS = "Настройки"
BTN_STOP = "Стоп"
BTN_HELP = "Помощь"


HELP_TEXT = (
    "<b>Команды бота</b>\n\n"
    "/search — запустить новый поиск тендеров\n"
    "/settings — показать текущие критерии\n"
    "/стоп — остановить текущий поиск\n"
    "/help — эта справка\n\n"
    "<b>Настройки</b>\n"
    "Используйте кнопки ниже для изменения критериев, "
    "ключевых слов и площадок."
)


# ==========================================================
# НАЗВАНИЯ ПЛОЩАДОК
# ==========================================================

PLATFORM_NAMES = {
    "eis": "ЕИС",
    "b2b_center": "B2B-Center",
    "rts_tender": "РТС-тендер",
    "tmk": "ТМК",
    "unipro": "UniPro",
}


class TelegramBot:
    """Простой long-polling Telegram-бот."""

    def __init__(
        self,
        settings: AppSettings,
        orchestrator: Orchestrator,
    ) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self.criteria_store = orchestrator.criteria_store

        self.bot_token = settings.telegram_bot_token
        self.allowed_chat_id = str(
            settings.telegram_chat_id
        ).strip()

        self._offset: int | None = None

        # Какой критерий сейчас ожидает ввода.
        self._waiting_for: dict[str, str] = {}

        # Поиск запускается отдельно от long polling.
        self._search_thread: threading.Thread | None = None

    # ==========================================================
    # TELEGRAM API
    # ==========================================================

    def _call(self, method: str, **params) -> dict:
        url = TELEGRAM_API.format(
            token=self.bot_token,
            method=method,
        )

        with httpx.Client(timeout=40.0) as client:
            response = client.post(
                url,
                json=params,
            )
            response.raise_for_status()
            return response.json()

    def _send(
        self,
        chat_id: str,
        text: str,
        reply_markup: dict | None = None,
    ) -> dict | None:
        try:
            params = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }

            if reply_markup is not None:
                params["reply_markup"] = reply_markup

            return self._call(
                "sendMessage",
                **params,
            )

        except httpx.HTTPError as exc:
            logger.error(
                "Telegram-бот: ошибка отправки: %s",
                exc,
            )
            return None

    def _answer_callback(
        self,
        callback_query_id: str,
    ) -> None:
        try:
            self._call(
                "answerCallbackQuery",
                callback_query_id=callback_query_id,
            )
        except httpx.HTTPError as exc:
            logger.error(
                "Telegram-бот: ошибка callback: %s",
                exc,
            )

    # ==========================================================
    # ОСНОВНАЯ КЛАВИАТУРА
    # ==========================================================

    @staticmethod
    def _keyboard() -> dict:
        return {
            "keyboard": [
                [
                    {"text": BTN_PRICE_FROM},
                    {"text": BTN_PRICE_TO},
                ],
                [
                    {"text": BTN_SCORE},
                    {"text": BTN_DAYS},
                ],
                [
                    {"text": BTN_KEYWORDS},
                    {"text": BTN_PLATFORMS},
                ],
                [
                    {"text": BTN_RESET},
                ],
                [
                    {"text": BTN_SEARCH},
                    {"text": BTN_SETTINGS},
                ],
                [
                    {"text": BTN_STOP},
                    {"text": BTN_HELP},
                ],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
        }

    # ==========================================================
    # POLLING
    # ==========================================================

    def run_polling(self) -> None:
        if not self.bot_token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN не задан в .env — "
                "бот не может запуститься."
            )

        if not self.allowed_chat_id:
            raise RuntimeError(
                "TELEGRAM_CHAT_ID не задан в .env — "
                "бот не знает, кому отвечать."
            )

        logger.info(
            "Telegram-бот запущен. Разрешённый chat_id: %s",
            self.allowed_chat_id,
        )

        self._send(
            self.allowed_chat_id,
            "Бот запущен.\n\n" + HELP_TEXT,
            reply_markup=self._keyboard(),
        )

        while True:
            try:
                self._poll_once()

            except KeyboardInterrupt:
                logger.info(
                    "Telegram-бот остановлен (Ctrl+C)"
                )
                break

            except Exception:
                logger.exception(
                    "Telegram-бот: ошибка polling, "
                    "продолжаем через 5 сек"
                )
                time.sleep(5)

    def _poll_once(self) -> None:
        params: dict = {
            "timeout": 30,
            "allowed_updates": [
                "message",
                "callback_query",
            ],
        }

        if self._offset is not None:
            params["offset"] = self._offset

        result = self._call(
            "getUpdates",
            **params,
        )

        for update in result.get("result", []):
            self._offset = update["update_id"] + 1

            if "callback_query" in update:
                self._handle_callback(
                    update["callback_query"]
                )
                continue

            message = update.get("message")

            if not message:
                continue

            self._handle_message(message)

    # ==========================================================
    # CALLBACK QUERY
    # ==========================================================

    def _handle_callback(
        self,
        callback: dict,
    ) -> None:
        callback_id = str(
            callback.get("id", "")
        )

        data = str(
            callback.get("data", "")
        )

        message = callback.get("message") or {}

        chat_id = str(
            message.get("chat", {}).get("id", "")
        )

        if not chat_id or chat_id != self.allowed_chat_id:
            self._answer_callback(callback_id)
            return

        logger.info(
            "Telegram-бот: callback=%s",
            data,
        )

        try:
            if data == "platform:close":
                self._answer_callback(callback_id)

                self._send(
                    chat_id,
                    "Настройки площадок закрыты.",
                    reply_markup=self._keyboard(),
                )

                return

            elif data.startswith("platform:"):
                platform = data.split(
                    ":",
                    1,
                )[1]

                self._toggle_platform(
                    chat_id,
                    platform,
                )

            elif data == "keywords:clear":
                self.criteria_store.set_keywords([])

                self._answer_callback(
                    callback_id
                )

                self._send(
                    chat_id,
                    "Ключевые слова очищены.",
                    reply_markup=self._keyboard(),
                )

                return

            elif data == "keywords:edit":
                self._answer_callback(
                    callback_id
                )

                self._ask_value(
                    chat_id,
                    "keywords",
                    "Введите ключевые слова через запятую.\n\n"
                    "Например:\n"
                    "<code>подшипники, муфты, "
                    "запасные части</code>\n\n"
                    "Если хотите искать по одному слову — "
                    "введите только его.",
                )

                return

            self._answer_callback(
                callback_id
            )

        except Exception:
            logger.exception(
                "Telegram-бот: ошибка обработки callback=%s",
                data,
            )

            self._answer_callback(
                callback_id
            )

    # ==========================================================
    # ПЛОЩАДКИ
    # ==========================================================

    def _platform_keyboard(self) -> dict:
        enabled = set(
            self.criteria_store.get_enabled_platforms()
        )

        rows = []

        for platform, name in PLATFORM_NAMES.items():
            mark = "☑" if platform in enabled else "☐"

            rows.append(
                [
                    {
                        "text": f"{mark} {name}",
                        "callback_data": (
                            f"platform:{platform}"
                        ),
                    }
                ]
            )

        rows.append(
            [
                {
                    "text": "Закрыть",
                    "callback_data": "platform:close",
                }
            ]
        )

        return {
            "inline_keyboard": rows
        }

    def _show_platforms(
        self,
        chat_id: str,
    ) -> None:
        enabled = set(
            self.criteria_store.get_enabled_platforms()
        )

        lines = [
            "<b>Площадки поиска</b>",
            "",
            "Нажмите на площадку, чтобы "
            "включить или выключить её.",
            "",
        ]

        for platform, name in PLATFORM_NAMES.items():
            if platform in enabled:
                lines.append(
                    f"☑ {name}"
                )
            else:
                lines.append(
                    f"☐ {name}"
                )

        lines.extend(
            [
                "",
                "<i>Сейчас реально подключена только ЕИС.</i>",
                "<i>Остальные площадки пока можно "
                "настраивать, но поиск по ним ещё "
                "не выполняется.</i>",
            ]
        )

        self._send(
            chat_id,
            "\n".join(lines),
            reply_markup=self._platform_keyboard(),
        )

    def _toggle_platform(
        self,
        chat_id: str,
        platform: str,
    ) -> None:
        if platform not in PLATFORM_NAMES:
            return

        current = set(
            self.criteria_store.get_enabled_platforms()
        )

        if platform in current:
            current.remove(platform)
        else:
            current.add(platform)

        # Не даём отключить ЕИС, пока она единственная
        # реально работающая площадка.
        if (
            platform == "eis"
            and platform not in current
        ):
            current.add("eis")

            self._send(
                chat_id,
                "ЕИС пока нельзя отключить: "
                "это единственная подключённая "
                "к поиску площадка.",
                reply_markup=self._keyboard(),
            )

            self._show_platforms(chat_id)
            return

        self.criteria_store.set_enabled_platforms(
            list(current)
        )

        self._show_platforms(chat_id)

    # ==========================================================
    # КЛЮЧЕВЫЕ СЛОВА
    # ==========================================================

    def _show_keywords(
        self,
        chat_id: str,
    ) -> None:
        keywords = (
            self.criteria_store.get_keywords()
        )

        if keywords:
            lines = [
                "<b>Ключевые слова</b>",
                "",
                "Сейчас заданы:",
                "",
            ]

            for index, keyword in enumerate(
                keywords,
                start=1,
            ):
                lines.append(
                    f"{index}. {keyword}"
                )

            lines.extend(
                [
                    "",
                    "При наличии пользовательских "
                    "ключевых слов поиск будет "
                    "ориентироваться на них.",
                ]
            )

        else:
            lines = [
                "<b>Ключевые слова</b>",
                "",
                "Пользовательские ключевые слова "
                "не заданы.",
                "",
                "Сейчас используются ключевые слова "
                "из config/keywords.yaml.",
            ]

        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "Изменить",
                        "callback_data": "keywords:edit",
                    }
                ],
                [
                    {
                        "text": "Очистить",
                        "callback_data": "keywords:clear",
                    }
                ],
            ]
        }

        self._send(
            chat_id,
            "\n".join(lines),
            reply_markup=keyboard,
        )

    # ==========================================================
    # ОБРАБОТКА СООБЩЕНИЙ
    # ==========================================================

    def _handle_message(
        self,
        message: dict,
    ) -> None:
        chat_id = str(
            message.get("chat", {}).get("id", "")
        )

        text = (
            message.get("text") or ""
        ).strip()

        if not text:
            return

        if chat_id != self.allowed_chat_id:
            logger.warning(
                "Telegram-бот: сообщение от постороннего "
                "chat_id=%s — игнорируем",
                chat_id,
            )
            return

        logger.info(
            "Telegram-бот: получено сообщение: %s",
            text,
        )

        try:
            # --------------------------------------------------
            # Сначала проверяем ожидаемый ввод.
            # --------------------------------------------------

            if chat_id in self._waiting_for:
                # Основные кнопки меню не должны восприниматься
                # как значение вводимого параметра.
                menu_buttons = {
                    BTN_PRICE_FROM,
                    BTN_PRICE_TO,
                    BTN_SCORE,
                    BTN_DAYS,
                    BTN_KEYWORDS,
                    BTN_PLATFORMS,
                    BTN_RESET,
                    BTN_SEARCH,
                    BTN_SETTINGS,
                    BTN_STOP,
                    BTN_HELP,
                }

                if text not in menu_buttons:
                    if self._handle_value_input(
                        chat_id,
                        text,
                    ):
                        return

                # Нажата кнопка меню — отменяем ожидание ввода.
                self._waiting_for.pop(chat_id, None)

            # --------------------------------------------------
            # Команды
            # --------------------------------------------------

            if (
                text.startswith("/start")
                or text.startswith("/help")
                or text == BTN_HELP
            ):
                self._cmd_help(chat_id)

            elif (
                text.startswith("/settings")
                or text == BTN_SETTINGS
            ):
                self._cmd_settings(chat_id)

            elif (
                text.startswith("/search")
                or text.startswith("/run")
                or text == BTN_SEARCH
            ):
                self._cmd_search(chat_id)

            elif (
                text.startswith("/стоп")
                or text.startswith("/stop")
                or text == BTN_STOP
            ):
                self._cmd_stop(chat_id)

            # --------------------------------------------------
            # Кнопки критериев
            # --------------------------------------------------

            elif text == BTN_PRICE_FROM:
                self._ask_value(
                    chat_id,
                    "min_price",
                    "Введите минимальную цену.\n\n"
                    "Например:\n"
                    "<code>100000</code>",
                )

            elif text == BTN_PRICE_TO:
                self._ask_value(
                    chat_id,
                    "max_price",
                    "Введите максимальную цену.\n\n"
                    "Например:\n"
                    "<code>5000000</code>",
                )

            elif text == BTN_SCORE:
                self._ask_value(
                    chat_id,
                    "min_ai_score",
                    "Введите минимальный балл AI.\n\n"
                    "Например:\n"
                    "<code>70</code>",
                )

            elif text == BTN_DAYS:
                self._ask_value(
                    chat_id,
                    "min_submission_days",
                    "Введите минимальное количество "
                    "дней до дедлайна.\n\n"
                    "Например:\n"
                    "<code>7</code>",
                )

            elif text == BTN_KEYWORDS:
                self._show_keywords(chat_id)

            elif text == BTN_PLATFORMS:
                self._show_platforms(chat_id)

            elif text == BTN_RESET:
                self._cmd_reset(chat_id)

            else:
                self._send(
                    chat_id,
                    "Не понял команду.\n\n"
                    "Используйте кнопки ниже или /help.",
                    reply_markup=self._keyboard(),
                )

        except Exception:
            logger.exception(
                "Telegram-бот: ошибка обработки: %s",
                text,
            )

            self._send(
                chat_id,
                "Что-то пошло не так при обработке команды.\n"
                "Подробности — в logs/agent.log.",
                reply_markup=self._keyboard(),
            )

    # ==========================================================
    # ВВОД ЗНАЧЕНИЙ
    # ==========================================================

    def _ask_value(
        self,
        chat_id: str,
        field: str,
        message: str,
    ) -> None:
        self._waiting_for[chat_id] = field

        self._send(
            chat_id,
            message,
            reply_markup=self._keyboard(),
        )

    def _handle_value_input(
        self,
        chat_id: str,
        text: str,
    ) -> bool:
        field = self._waiting_for.get(chat_id)

        if not field:
            return False

        # ------------------------------------------------------
        # Ключевые слова
        # ------------------------------------------------------

        if field == "keywords":
            values = [
                item.strip()
                for item in text.split(",")
                if item.strip()
            ]

            if not values:
                self._send(
                    chat_id,
                    "Не удалось найти ключевые слова.\n\n"
                    "Введите их через запятую.",
                    reply_markup=self._keyboard(),
                )
                return True

            self.criteria_store.set_keywords(
                values
            )

            del self._waiting_for[chat_id]

            self._send(
                chat_id,
                "<b>Ключевые слова сохранены.</b>\n\n"
                + "\n".join(
                    f"• {keyword}"
                    for keyword in values
                ),
                reply_markup=self._keyboard(),
            )

            return True

        # ------------------------------------------------------
        # Числовые критерии
        # ------------------------------------------------------

        raw_value = text.strip()

        if ":" in raw_value:
            raw_value = raw_value.split(
                ":",
                1,
            )[1].strip()

        try:
            if field in (
                "min_price",
                "max_price",
            ):
                value = float(
                    raw_value.replace(
                        " ",
                        "",
                    ).replace(
                        ",",
                        ".",
                    )
                )

                if value < 0:
                    raise ValueError

            else:
                value = int(raw_value)

                if value < 0:
                    raise ValueError

        except ValueError:
            self._send(
                chat_id,
                "Некорректное значение.\n\n"
                "Введите число ещё раз.",
                reply_markup=self._keyboard(),
            )
            return True

        self.criteria_store.update(
            **{field: value}
        )

        del self._waiting_for[chat_id]

        labels = {
            "min_price": "Цена от",
            "max_price": "Цена до",
            "min_ai_score": "Балл",
            "min_submission_days": "Срок",
        }

        label = labels[field]

        if isinstance(value, float) and value.is_integer():
            display_value = str(
                int(value)
            )
        else:
            display_value = str(value)

        self._send(
            chat_id,
            f"<b>{label}:</b> {display_value}\n\n"
            "Критерий сохранён.\n"
            "Новый поиск будет использовать "
            "это значение.",
            reply_markup=self._keyboard(),
        )

        return True

    # ==========================================================
    # SETTINGS
    # ==========================================================

    def _cmd_settings(
        self,
        chat_id: str,
    ) -> None:
        c = self.criteria_store.get()
        keywords = self.criteria_store.get_keywords()
        platforms = self.criteria_store.get_enabled_platforms()

        def fmt_price(value) -> str:
            if value is None:
                return "не задано"

            value = float(value)

            if value.is_integer():
                return f"{int(value):,}".replace(
                    ",",
                    " ",
                )

            return str(value)

        platform_names = [
            PLATFORM_NAMES.get(
                platform,
                platform,
            )
            for platform in platforms
        ]

        if keywords:
            keywords_text = ", ".join(
                keywords
            )
        else:
            keywords_text = (
                "из config/keywords.yaml"
            )

        text = (
            "<b>Текущие критерии поиска</b>\n\n"
            f"Цена от: {fmt_price(c.min_price)}\n"
            f"Цена до: {fmt_price(c.max_price)}\n"
            f"Балл: {c.min_ai_score}\n"
            f"Срок: {c.min_submission_days} дн.\n"
            f"Ключевые слова: {keywords_text}\n"
            f"Площадки: "
            f"{', '.join(platform_names)}\n\n"
            "Измените нужный параметр кнопками ниже."
        )

        self._send(
            chat_id,
            text,
            reply_markup=self._keyboard(),
        )

    # ==========================================================
    # СБРОС
    # ==========================================================

    def _cmd_reset(
        self,
        chat_id: str,
    ) -> None:
        self.criteria_store.update(
            min_price=None,
            max_price=None,
            min_ai_score=70,
            min_submission_days=7,
        )

        self.criteria_store.set_keywords([])

        self.criteria_store.set_enabled_platforms(
            ["eis"]
        )

        self._waiting_for.pop(
            chat_id,
            None,
        )

        self._send(
            chat_id,
            "<b>Критерии поиска сброшены.</b>\n\n"
            "Цена от: не задано\n"
            "Цена до: не задано\n"
            "Балл: 70\n"
            "Срок: 7 дн.\n"
            "Ключевые слова: из config/keywords.yaml\n"
            "Площадки: ЕИС\n\n"
            "Следующий поиск будет выполнен "
            "с этими значениями.",
            reply_markup=self._keyboard(),
        )

    # ==========================================================
    # ПОИСК
    # ==========================================================

    def _cmd_search(
        self,
        chat_id: str,
    ) -> None:
        if (
            self._search_thread is not None
            and self._search_thread.is_alive()
        ):
            self._send(
                chat_id,
                "Поиск уже выполняется.\n\n"
                "Если нужно остановить его — нажмите "
                "«Стоп» или отправьте /стоп.",
                reply_markup=self._keyboard(),
            )
            return

        self._send(
            chat_id,
            "Запускаю новый поиск тендеров.\n\n"
            "Поиск выполняется в фоне. "
            "Бот продолжит принимать команды.\n\n"
            "Для остановки нажмите «Стоп» "
            "или отправьте /стоп.",
            reply_markup=self._keyboard(),
        )

        self.orchestrator.clear_stop_request()

        self._search_thread = threading.Thread(
            target=self._run_search,
            args=(chat_id,),
            daemon=True,
            name="telegram-search",
        )

        self._search_thread.start()

    def _run_search(
        self,
        chat_id: str,
    ) -> None:
        """Запускает поиск в фоне и сообщает результат в Telegram."""

        import time

        started_at = time.monotonic()

        self._send(
            chat_id,
            "🔄 <b>Поиск выполняется...</b>\n\n"
            "Поиск запущен.\n"
            "Идёт сбор и анализ тендеров.\n\n"
            "⏳ Пожалуйста, подождите...",
            reply_markup=self._keyboard(),
        )

        try:
            stats = self.orchestrator.run_cycle()

            elapsed = int(time.monotonic() - started_at)
            minutes = elapsed // 60
            seconds = elapsed % 60

            if minutes:
                elapsed_text = f"{minutes} мин. {seconds:02d} сек."
            else:
                elapsed_text = f"{seconds} сек."

            if self.orchestrator.stop_requested:
                final_text = (
                    f"⛔ <b>Поиск №{stats['search_number']:03d} остановлен.</b>\n\n"
                    f"Время работы: {elapsed_text}\n\n"
                    f"Найдено на площадках: {stats['found']}\n"
                    f"Прошло фильтр по ключевым словам: {stats['filtered']}\n"
                    f"Новых тендеров: {stats['new']}\n"
                    f"Проанализировано AI: {stats['analyzed']}\n"
                    f"Отправлено уведомлений: {stats['notified']}\n"
                    f"Пропущено дублей: {stats['skipped_duplicate']}\n"
                    f"Исключено по критериям: {stats['excluded_by_criteria']}"
                )
            else:
                final_text = (
                    f"✅ <b>Поиск №{stats['search_number']:03d} завершён.</b>\n\n"
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

            self._send(
                chat_id,
                final_text,
                reply_markup=self._keyboard(),
            )

        except Exception:
            logger.exception(
                "Telegram-бот: ошибка выполнения поиска"
            )

            self._send(
                chat_id,
                "❌ <b>Ошибка поиска.</b>\n\n"
                "Подробности находятся в logs/agent.log.",
                reply_markup=self._keyboard(),
            )
    # ==========================================================
    # СТОП
    # ==========================================================

    def _cmd_stop(
        self,
        chat_id: str,
    ) -> None:
        if (
            self._search_thread is None
            or not self._search_thread.is_alive()
        ):
            self._send(
                chat_id,
                "Сейчас поиск не выполняется.",
                reply_markup=self._keyboard(),
            )
            return

        self.orchestrator.request_stop()

        self._send(
            chat_id,
            "Получена команда остановки.\n\n"
            "Текущий этап завершится, после чего поиск "
            "будет остановлен.",
            reply_markup=self._keyboard(),
        )

    # ==========================================================
    # HELP
    # ==========================================================

    def _cmd_help(
        self,
        chat_id: str,
    ) -> None:
        self._send(
            chat_id,
            HELP_TEXT,
            reply_markup=self._keyboard(),
        )

    # ==========================================================
    # STATUS
    # ==========================================================

    def _cmd_status(
        self,
        chat_id: str,
    ) -> None:
        db = self.orchestrator.db

        text = (
            "<b>Статус агента</b>\n\n"
            f"Тендеров в базе: "
            f"{db.count_tenders()}\n"
            f"Отправлено уведомлений всего: "
            f"{db.count_notifications()}\n"
            f"AI: {self.settings.ai_model} "
            f"({self.settings.ai_provider})\n"
            "Telegram: "
            f"{'настроен' if self.settings.telegram_bot_token else 'dry-run'}"
        )

        self._send(
            chat_id,
            text,
            reply_markup=self._keyboard(),
        )







