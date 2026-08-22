"""Многопользовательский runtime Telegram-бота с белым списком доступа."""
from __future__ import annotations

import logging
import os
import threading
import time

from src.orchestrator import Orchestrator
from src.telegram_bot import TelegramBot

logger = logging.getLogger(__name__)


class MultiUserTelegramBot(TelegramBot):
    """TelegramBot с независимыми поисками и контролем доступа по Telegram ID.

    Администратор из TELEGRAM_CHAT_ID всегда разрешён. Дополнительные
    пользователи задаются в TELEGRAM_ALLOWED_USER_IDS через запятую.
    Пустой список означает безопасный режим: доступ есть только у админа.
    """

    def __init__(self, settings, orchestrator: Orchestrator) -> None:
        super().__init__(settings, orchestrator)
        self._search_threads: dict[str, threading.Thread] = {}
        self._user_orchestrators: dict[str, Orchestrator] = {}
        self._search_lock = threading.Lock()
        self._allowed_user_ids = self._load_allowed_user_ids()

        logger.info(
            "Telegram-доступ: whitelist включён; разрешённых пользователей=%d",
            len(self._allowed_user_ids),
        )

    def _load_allowed_user_ids(self) -> set[str]:
        raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
        allowed = {
            item.strip()
            for item in raw.split(",")
            if item.strip()
        }
        if self.admin_chat_id:
            allowed.add(self.admin_chat_id)
        return allowed

    def _is_allowed(self, chat_id: str) -> bool:
        return str(chat_id).strip() in self._allowed_user_ids

    def _access_denied(self, chat_id: str) -> None:
        self._send(
            chat_id,
            "🔒 <b>Доступ ограничен.</b>\n\n"
            "У вас нет разрешения на использование этого бота.\n\n"
            "Если вы должны получить доступ, обратитесь к администратору.",
        )

    def _handle_message(self, message: dict) -> None:
        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id and not self._is_allowed(chat_id):
            logger.warning(
                "Telegram-доступ: отказ пользователю chat_id=%s",
                chat_id,
            )
            self._access_denied(chat_id)
            return
        super()._handle_message(message)

    def _handle_callback(self, callback: dict) -> None:
        message = callback.get("message") or {}
        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id and not self._is_allowed(chat_id):
            self._answer_callback(str(callback.get("id", "")))
            self._access_denied(chat_id)
            return
        super()._handle_callback(callback)

    def _cmd_search(self, chat_id: str) -> None:
        with self._search_lock:
            thread = self._search_threads.get(chat_id)
            if thread is not None and thread.is_alive():
                self._send(
                    chat_id,
                    "Поиск уже выполняется для вашего аккаунта.\n\n"
                    "Если нужно остановить его — нажмите «Стоп».",
                    self._keyboard(),
                )
                return

            orchestrator = Orchestrator(self.settings)
            orchestrator.notifier.chat_id = chat_id
            self._user_orchestrators[chat_id] = orchestrator
            orchestrator.clear_stop_request()

            self._send(
                chat_id,
                "Запускаю новый поиск тендеров.\n\n"
                "Поиск выполняется в фоне.",
                self._keyboard(),
            )

            thread = threading.Thread(
                target=self._run_search_for_user,
                args=(chat_id, orchestrator),
                daemon=True,
                name=f"telegram-search-{chat_id}",
            )
            self._search_threads[chat_id] = thread
            thread.start()

    def _run_search_for_user(self, chat_id: str, orchestrator: Orchestrator) -> None:
        started_at = time.monotonic()
        self._send(
            chat_id,
            "🔄 <b>Поиск выполняется...</b>\n\n"
            "Идёт сбор и анализ тендеров.\n\n"
            "⏳ Пожалуйста, подождите...",
            self._keyboard(),
        )
        try:
            stats = orchestrator.run_cycle()
            elapsed = int(time.monotonic() - started_at)
            elapsed_text = (
                f"{elapsed // 60} мин. {elapsed % 60:02d} сек."
                if elapsed >= 60
                else f"{elapsed} сек."
            )
            state = "остановлен" if orchestrator.stop_requested else "завершён"
            text = (
                f"{'⛔' if orchestrator.stop_requested else '✅'} "
                f"<b>Поиск №{stats['search_number']:03d} {state}.</b>\n\n"
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
            logger.exception("Telegram-бот: ошибка выполнения поиска chat_id=%s", chat_id)
            self._send(
                chat_id,
                "❌ <b>Ошибка поиска.</b>\n\n"
                "Подробности находятся в logs/agent.log.",
                self._keyboard(),
            )
        finally:
            with self._search_lock:
                self._search_threads.pop(chat_id, None)
                self._user_orchestrators.pop(chat_id, None)

    def _cmd_stop(self, chat_id: str) -> None:
        with self._search_lock:
            orchestrator = self._user_orchestrators.get(chat_id)
            thread = self._search_threads.get(chat_id)

        if orchestrator is None or thread is None or not thread.is_alive():
            self._send(chat_id, "Сейчас ваш поиск не выполняется.", self._keyboard())
            return

        orchestrator.request_stop()
        self._send(
            chat_id,
            "Получена команда остановки. Текущий этап завершится, после чего ваш поиск будет остановлен.",
            self._keyboard(),
        )
