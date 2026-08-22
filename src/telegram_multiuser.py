"""Многопользовательский runtime Telegram-бота с белым списком доступа."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from src.orchestrator import Orchestrator
from src.telegram_bot import TelegramBot

logger = logging.getLogger(__name__)

# Постоянный владелец бота. Этот ID всегда имеет доступ.
OWNER_TELEGRAM_ID = "838120236"
WHITELIST_FILE = Path("data/telegram_allowed_users.json")


class MultiUserTelegramBot(TelegramBot):
    """TelegramBot с независимыми поисками и управлением белым списком."""

    def __init__(self, settings, orchestrator: Orchestrator) -> None:
        super().__init__(settings, orchestrator)
        self._search_threads: dict[str, threading.Thread] = {}
        self._user_orchestrators: dict[str, Orchestrator] = {}
        self._search_lock = threading.Lock()
        self._whitelist_lock = threading.Lock()
        self._allowed_user_ids = self._load_allowed_user_ids()
        logger.info(
            "Telegram-доступ: whitelist включён; разрешённых пользователей=%d",
            len(self._allowed_user_ids),
        )

    def _load_allowed_user_ids(self) -> set[str]:
        allowed = {item.strip() for item in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if item.strip()}
        try:
            if WHITELIST_FILE.exists():
                data = json.loads(WHITELIST_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    allowed.update(str(x).strip() for x in data if str(x).strip())
        except Exception:
            logger.exception("Telegram-доступ: не удалось прочитать %s", WHITELIST_FILE)
        allowed.add(OWNER_TELEGRAM_ID)
        if self.admin_chat_id:
            allowed.add(self.admin_chat_id)
        return allowed

    def _save_allowed_user_ids(self) -> None:
        WHITELIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        users = sorted(x for x in self._allowed_user_ids if x != OWNER_TELEGRAM_ID)
        WHITELIST_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")

    def _is_owner(self, chat_id: str) -> bool:
        return str(chat_id).strip() == OWNER_TELEGRAM_ID

    def _is_allowed(self, chat_id: str) -> bool:
        return str(chat_id).strip() in self._allowed_user_ids

    def _access_denied(self, chat_id: str) -> None:
        user_id = str(chat_id).strip()
        self._send(
            chat_id,
            "🔒 <b>Доступ ограничен.</b>\n\n"
            "У вас пока нет разрешения на использование этого бота.\n\n"
            f"Ваш Telegram ID: <code>{user_id}</code>\n\n"
            "Передайте этот ID администратору. После добавления в белый список "
            "бот станет доступен вам автоматически.",
        )

    def _admin_menu(self, chat_id: str) -> None:
        self._send(
            chat_id,
            "<b>👑 Управление доступом</b>\n\n"
            "➕ Добавить пользователя — <code>/add_user ID</code>\n"
            "➖ Удалить пользователя — <code>/remove_user ID</code>\n"
            "📋 Список пользователей — <code>/users</code>\n\n"
            "Пример:\n<code>/add_user 1378791558</code>",
            self._keyboard(),
        )

    def _admin_command(self, chat_id: str, text: str) -> bool:
        if not self._is_owner(chat_id):
            return False
        parts = text.strip().split()
        command = parts[0].lower() if parts else ""
        if command in {"/admin", "/users", "/пользователи"}:
            if command != "/admin":
                users = sorted(self._allowed_user_ids)
                lines = ["<b>👥 Разрешённые пользователи</b>", "", f"Всего: {len(users)}"]
                for user_id in users:
                    suffix = " — владелец" if user_id == OWNER_TELEGRAM_ID else ""
                    lines.append(f"• <code>{user_id}</code>{suffix}")
                self._send(chat_id, "\n".join(lines), self._keyboard())
            else:
                self._admin_menu(chat_id)
            return True
        if command in {"/add_user", "/добавить"}:
            if len(parts) != 2 or not parts[1].isdigit():
                self._send(chat_id, "Формат: <code>/add_user 123456789</code>", self._keyboard())
                return True
            user_id = parts[1]
            with self._whitelist_lock:
                self._allowed_user_ids.add(user_id)
                self._save_allowed_user_ids()
            self._send(chat_id, f"✅ Пользователь <code>{user_id}</code> добавлен в белый список.", self._keyboard())
            return True
        if command in {"/remove_user", "/удалить"}:
            if len(parts) != 2 or not parts[1].isdigit():
                self._send(chat_id, "Формат: <code>/remove_user 123456789</code>", self._keyboard())
                return True
            user_id = parts[1]
            if user_id == OWNER_TELEGRAM_ID:
                self._send(chat_id, "⛔ Владельца удалить нельзя. Ваш доступ постоянный.", self._keyboard())
                return True
            with self._whitelist_lock:
                self._allowed_user_ids.discard(user_id)
                self._save_allowed_user_ids()
            self._send(chat_id, f"✅ Пользователь <code>{user_id}</code> удалён из белого списка.", self._keyboard())
            return True
        return False

    def _handle_message(self, message: dict) -> None:
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = (message.get("text") or "").strip()
        if not chat_id:
            return
        if self._admin_command(chat_id, text):
            return
        if not self._is_allowed(chat_id):
            logger.warning("Telegram-доступ: отказ пользователю chat_id=%s", chat_id)
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
                self._send(chat_id, "Поиск уже выполняется для вашего аккаунта.\n\nЕсли нужно остановить его — нажмите «Стоп».", self._keyboard())
                return
            orchestrator = Orchestrator(self.settings)
            orchestrator.notifier.chat_id = chat_id
            self._user_orchestrators[chat_id] = orchestrator
            orchestrator.clear_stop_request()
            self._send(chat_id, "Запускаю новый поиск тендеров.\n\nПоиск выполняется в фоне.", self._keyboard())
            thread = threading.Thread(target=self._run_search_for_user, args=(chat_id, orchestrator), daemon=True, name=f"telegram-search-{chat_id}")
            self._search_threads[chat_id] = thread
            thread.start()

    def _run_search_for_user(self, chat_id: str, orchestrator: Orchestrator) -> None:
        started_at = time.monotonic()
        self._send(chat_id, "🔄 <b>Поиск выполняется...</b>\n\nИдёт сбор и анализ тендеров.\n\n⏳ Пожалуйста, подождите...", self._keyboard())
        try:
            stats = orchestrator.run_cycle()
            elapsed = int(time.monotonic() - started_at)
            elapsed_text = f"{elapsed // 60} мин. {elapsed % 60:02d} сек." if elapsed >= 60 else f"{elapsed} сек."
            state = "остановлен" if orchestrator.stop_requested else "завершён"
            text = (
                f"{'⛔' if orchestrator.stop_requested else '✅'} <b>Поиск №{stats['search_number']:03d} {state}.</b>\n\n"
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
            self._send(chat_id, "❌ <b>Ошибка поиска.</b>\n\nПодробности находятся в logs/agent.log.", self._keyboard())
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
        self._send(chat_id, "Получена команда остановки. Текущий этап завершится, после чего ваш поиск будет остановлен.", self._keyboard())
