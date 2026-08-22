"""Многопользовательский runtime для Telegram-бота.

Базовый TelegramBot отвечает за интерфейс и хранение настроек. Этот слой
разделяет запущенные поиски по chat_id, создаёт отдельный Orchestrator для
каждого пользователя и направляет найденные тендеры пользователю, который
запустил поиск, а не только владельцу TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import logging
import threading
import time

from src.orchestrator import Orchestrator
from src.telegram_bot import TelegramBot

logger = logging.getLogger(__name__)


class MultiUserTelegramBot(TelegramBot):
    """TelegramBot с независимыми поисками для каждого пользователя."""

    def __init__(self, settings, orchestrator: Orchestrator) -> None:
        super().__init__(settings, orchestrator)
        self._search_threads: dict[str, threading.Thread] = {}
        self._user_orchestrators: dict[str, Orchestrator] = {}
        self._search_lock = threading.Lock()

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
            # Уведомления этого конкретного поиска должны идти пользователю,
            # который его запустил. Админский TELEGRAM_CHAT_ID при этом
            # продолжает использоваться для служебного сообщения при старте.
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
