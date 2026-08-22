"""Многопользовательский runtime Telegram-бота с белым списком доступа."""
from __future__ import annotations

import html
import json
import logging
import os
import threading
import time
from pathlib import Path

from src.orchestrator import Orchestrator
from src.telegram_bot import TelegramBot

logger = logging.getLogger(__name__)
OWNER_TELEGRAM_ID = "838120236"
WHITELIST_FILE = Path("data/telegram_allowed_users.json")
BTN_ADMIN = "👑 Управление доступом"
BTN_ADMIN_ADD = "➕ Добавить пользователя"
BTN_ADMIN_REMOVE = "➖ Удалить пользователя"
BTN_ADMIN_USERS = "📋 Список пользователей"
BTN_ADMIN_BACK = "↩️ Назад"


class MultiUserTelegramBot(TelegramBot):
    """TelegramBot с независимыми поисками и управлением белым списком."""
    def __init__(self, settings, orchestrator: Orchestrator) -> None:
        super().__init__(settings, orchestrator)
        self._search_threads: dict[str, threading.Thread] = {}
        self._user_orchestrators: dict[str, Orchestrator] = {}
        self._search_lock = threading.Lock()
        self._whitelist_lock = threading.Lock()
        self._admin_waiting: dict[str, str] = {}
        self._allowed_user_ids = self._load_allowed_user_ids()
        logger.info("Telegram-доступ: whitelist включён; разрешённых пользователей=%d", len(self._allowed_user_ids))

    def _load_allowed_user_ids(self) -> set[str]:
        allowed = {x.strip() for x in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if x.strip()}
        try:
            if WHITELIST_FILE.exists():
                data = json.loads(WHITELIST_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list): allowed.update(str(x).strip() for x in data if str(x).strip())
        except Exception: logger.exception("Telegram-доступ: не удалось прочитать %s", WHITELIST_FILE)
        allowed.add(OWNER_TELEGRAM_ID)
        if self.admin_chat_id: allowed.add(self.admin_chat_id)
        return allowed

    def _save_allowed_user_ids(self) -> None:
        WHITELIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        WHITELIST_FILE.write_text(json.dumps(sorted(x for x in self._allowed_user_ids if x != OWNER_TELEGRAM_ID), ensure_ascii=False, indent=2), encoding="utf-8")

    def _is_owner(self, chat_id: str) -> bool: return str(chat_id).strip() == OWNER_TELEGRAM_ID
    def _is_allowed(self, chat_id: str) -> bool: return str(chat_id).strip() in self._allowed_user_ids

    def _access_denied(self, chat_id: str) -> None:
        user_id = str(chat_id).strip()
        self._send(chat_id, "🔒 <b>Доступ ограничен.</b>\n\nУ вас пока нет разрешения на использование этого бота.\n\nВаш Telegram ID: <code>%s</code>" % user_id)

    def _admin_keyboard(self) -> dict:
        return {"keyboard": [[{"text": BTN_ADMIN_ADD}], [{"text": BTN_ADMIN_REMOVE}], [{"text": BTN_ADMIN_USERS}], [{"text": BTN_ADMIN_BACK}]], "resize_keyboard": True, "is_persistent": True}

    def _admin_menu(self, chat_id: str) -> None: self._send(chat_id, "<b>👑 Управление доступом</b>\n\nВыберите действие:", self._admin_keyboard())
    def _show_users(self, chat_id: str) -> None:
        users = sorted(self._allowed_user_ids); lines = ["<b>👥 Разрешённые пользователи</b>", "", f"Всего: {len(users)}", ""]
        lines.extend(f"• <code>{x}</code>{' — владелец' if x == OWNER_TELEGRAM_ID else ''}" for x in users)
        self._send(chat_id, "\n".join(lines), self._admin_keyboard())

    def _add_user(self, chat_id: str, user_id: str) -> None:
        with self._whitelist_lock: self._allowed_user_ids.add(user_id); self._save_allowed_user_ids()
        self._admin_waiting.pop(chat_id, None); self._send(chat_id, f"✅ Пользователь <code>{user_id}</code> добавлен.", self._admin_keyboard())
    def _remove_user(self, chat_id: str, user_id: str) -> None:
        if user_id == OWNER_TELEGRAM_ID: self._send(chat_id, "⛔ Владельца удалить нельзя.", self._admin_keyboard()); return
        with self._whitelist_lock: self._allowed_user_ids.discard(user_id); self._save_allowed_user_ids()
        self._admin_waiting.pop(chat_id, None); self._send(chat_id, f"✅ Пользователь <code>{user_id}</code> удалён.", self._admin_keyboard())

    def _admin_command(self, chat_id: str, text: str) -> bool:
        if not self._is_owner(chat_id): return False
        parts = text.strip().split(); command = parts[0].lower() if parts else ""
        if command == "/admin": self._admin_waiting.pop(chat_id, None); self._admin_menu(chat_id); return True
        if command in {"/users", "/пользователи"}: self._admin_waiting.pop(chat_id, None); self._show_users(chat_id); return True
        if command in {"/add_user", "/добавить"}: self._admin_waiting[chat_id] = "add"; self._send(chat_id, "Введите Telegram ID пользователя:", self._admin_keyboard()); return True
        if command in {"/remove_user", "/удалить"}: self._admin_waiting[chat_id] = "remove"; self._send(chat_id, "Введите Telegram ID пользователя:", self._admin_keyboard()); return True
        return False

    def _handle_message(self, message: dict) -> None:
        chat_id = str(message.get("chat", {}).get("id", "")); text = (message.get("text") or "").strip()
        if not chat_id: return
        if self._is_owner(chat_id) and chat_id in self._admin_waiting and text:
            if text == BTN_ADMIN_BACK: self._admin_waiting.pop(chat_id, None); self._send(chat_id, "Возвращаемся в основное меню.", self._keyboard()); return
            if text.isdigit():
                action = self._admin_waiting.get(chat_id); self._add_user(chat_id, text) if action == "add" else self._remove_user(chat_id, text); return
            self._send(chat_id, "Нужен числовой Telegram ID.", self._admin_keyboard()); return
        if self._is_owner(chat_id):
            if text == BTN_ADMIN: self._admin_menu(chat_id); return
            if text == BTN_ADMIN_ADD: self._admin_waiting[chat_id] = "add"; self._send(chat_id, "Введите Telegram ID пользователя:", self._admin_keyboard()); return
            if text == BTN_ADMIN_REMOVE: self._admin_waiting[chat_id] = "remove"; self._send(chat_id, "Введите Telegram ID пользователя:", self._admin_keyboard()); return
            if text == BTN_ADMIN_USERS: self._show_users(chat_id); return
            if text == BTN_ADMIN_BACK: self._send(chat_id, "Возвращаемся в основное меню.", self._keyboard()); return
            if self._admin_command(chat_id, text): return
        if not self._is_allowed(chat_id): self._access_denied(chat_id); return
        super()._handle_message(message)

    def _handle_callback(self, callback: dict) -> None:
        message = callback.get("message") or {}; chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id and not self._is_allowed(chat_id): self._answer_callback(str(callback.get("id", ""))); self._access_denied(chat_id); return
        super()._handle_callback(callback)

    def _cmd_search(self, chat_id: str) -> None:
        with self._search_lock:
            thread = self._search_threads.get(chat_id)
            if thread is not None and thread.is_alive(): self._send(chat_id, "Поиск уже выполняется.\n\nЕсли нужно остановить его — нажмите «Стоп`'.", self._keyboard()); return
            orchestrator = Orchestrator(self.settings); orchestrator.notifier.chat_id = chat_id; self._user_orchestrators[chat_id] = orchestrator; orchestrator.clear_stop_request()
            self._send(chat_id, "Запускаю новый поиск тендеров.\n\nПоиск выполняется в фоне.", self._keyboard())
            thread = threading.Thread(target=self._run_search_for_user, args=(chat_id, orchestrator), daemon=True, name=f"telegram-search-{chat_id}"); self._search_threads[chat_id] = thread; thread.start()

    def _send_search_results(self, chat_id: str, orchestrator: Orchestrator) -> None:
        results = orchestrator.last_run_results
        if not results:
            self._send(chat_id, "📭 <b>По результатам поиска подходящих тендеров нет.</b>", self._keyboard()); return
        self._send(chat_id, f"📋 <b>Результаты поиска: {len(results)}</b>", self._keyboard())
        for index, tender in enumerate(results, 1):
            price = f"{tender.price:,.0f} {tender.currency}".replace(",", " ") if tender.price is not None else "не указана"
            deadline = tender.deadline.strftime("%d.%m.%Y") if tender.deadline else "не указан"
            title = html.escape(tender.title or "Без названия")
            customer = html.escape(tender.customer or "не указан")
            url = html.escape(tender.url or "")
            text = f"<b>{index}. {title}</b>\n🏢 {customer}\n💰 {price}\n⏰ до {deadline}"
            if url: text += f'\n🔗 <a href="{url}">Открыть тендер</a>'
            self._send(chat_id, text, self._keyboard())

    def _run_search_for_user(self, chat_id: str, orchestrator: Orchestrator) -> None:
        started_at = time.monotonic(); self._send(chat_id, "🔄 <b>Поиск выполняется...</b>\n\nИдёт сбор и анализ тендеров.", self._keyboard())
        try:
            stats = orchestrator.run_cycle()
            self._send_search_results(chat_id, orchestrator)
            elapsed = int(time.monotonic() - started_at); elapsed_text = f"{elapsed // 60} мин. {elapsed % 60:02d} сек." if elapsed >= 60 else f"{elapsed} сек."
            state = "остановлен" if orchestrator.stop_requested else "завершён"
            text = f"{'⛔' if orchestrator.stop_requested else '✅'} <b>Поиск №{stats['search_number']:03d} {state}.</b>\n\nВремя: {elapsed_text}\nНайдено: {stats['found']}\nПрошло фильтр: {stats['filtered']}\nНовых: {stats['new']}\nAI: {stats['analyzed']}\nИсключено: {stats['excluded_by_criteria']}\nУведомлений: {stats['notified']}\nДублей: {stats['skipped_duplicate']}\n\n📊 Excel отправлен на почту."
            self._send(chat_id, text, self._keyboard())
        except Exception:
            logger.exception("Telegram-бот: ошибка выполнения поиска для chat_id=%s", chat_id); self._send(chat_id, "❌ <b>Ошибка поиска.</b>\n\nПодробности находятся в logs/agent.log.", self._keyboard())
        finally:
            with self._search_lock: self._search_threads.pop(chat_id, None); self._user_orchestrators.pop(chat_id, None)

    def _cmd_stop(self, chat_id: str) -> None:
        with self._search_lock: orchestrator = self._user_orchestrators.get(chat_id); thread = self._search_threads.get(chat_id)
        if orchestrator is None or thread is None or not thread.is_alive(): self._send(chat_id, "Сейчас ваш поиск не выполняется.", self._keyboard()); return
        orchestrator.request_stop(); self._send(chat_id, "Получена команда остановки. Текущий этап завершится, после чего ваш поиск будет остановлен.", self._keyboard())
