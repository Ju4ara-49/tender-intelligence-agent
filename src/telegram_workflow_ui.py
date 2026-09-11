"""Telegram UI для управления статусом, метками, комментариями и историей тендера."""
from __future__ import annotations

import html
import logging

from src.workflow import STATUS_NAMES, STATUSES

logger = logging.getLogger(__name__)


def _keyboard(tender_id: int, current_status: str) -> dict:
    buttons = []
    for status in STATUSES:
        if status == current_status:
            continue
        buttons.append({"text": STATUS_NAMES[status], "callback_data": f"workflow:status:{tender_id}:{status}"})
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.extend([
        [
            {"text": "🏷 Метки", "callback_data": f"workflow:tags:{tender_id}"},
            {"text": "💬 Комментарий", "callback_data": f"workflow:comment:{tender_id}"},
        ],
        [{"text": "🕘 История", "callback_data": f"workflow:history:{tender_id}"}],
    ])
    return {"inline_keyboard": rows}


def _show(bot, chat_id: str, tender_id: int) -> None:
    workflow = bot._workflow_store.get(tender_id, chat_id)
    text = (
        f"<b>Статус тендера #{tender_id}</b>\n\n"
        f"Текущий статус: <b>{html.escape(STATUS_NAMES.get(workflow.status, workflow.status))}</b>\n"
        f"Метки: {html.escape(', '.join(workflow.tags) if workflow.tags else 'нет')}\n"
        f"Комментарий: {html.escape(workflow.comment or 'нет')}"
    )
    bot._send(chat_id, text, _keyboard(tender_id, workflow.status))


def _show_history(bot, chat_id: str, tender_id: int) -> None:
    history = bot._workflow_store.history(tender_id, chat_id)
    if not history:
        bot._send(chat_id, f"<b>История тендера #{tender_id}</b>\n\nИзменений пока нет.", _back_keyboard(tender_id))
        return
    names = {"status": "статус", "tags": "метки", "comment": "комментарий"}
    lines = [f"<b>🕘 История тендера #{tender_id}</b>", ""]
    for item in history[-20:]:
        event = names.get(item["event_type"], item["event_type"])
        changed = html.escape(item["changed_at"].replace("T", " ").split("+", 1)[0])
        old = html.escape(item["old_value"] or "—")
        new = html.escape(item["new_value"] or "—")
        lines.append(f"<b>{changed}</b> — {event}: {old} → {new}")
    bot._send(chat_id, "\n".join(lines), _back_keyboard(tender_id))


def _back_keyboard(tender_id: int) -> dict:
    return {"inline_keyboard": [[{"text": "↩️ К тендеру", "callback_data": f"workflow:show:{tender_id}"}]]}


def install(bot_class) -> None:
    """Перехватывает workflow callback и ввод меток/комментариев."""
    if getattr(bot_class, "_workflow_ui_installed", False):
        return
    original_callback = bot_class._handle_callback
    original_message = bot_class._handle_message

    def handle_message(self, message):
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = (message.get("text") or "").strip()
        waiting = getattr(self, "_workflow_waiting", {}).get(chat_id)
        if waiting and text:
            tender_id, field = waiting
            try:
                if field == "tags":
                    tags = [item.strip() for item in text.split(",") if item.strip()]
                    state = self._workflow_store.set_tags(tender_id, chat_id, tags)
                    self._workflow_waiting.pop(chat_id, None)
                    self._send(chat_id, f"✅ Метки сохранены: <b>{html.escape(', '.join(state.tags) if state.tags else 'нет')}</b>", _keyboard(tender_id, state.status))
                    return
                if field == "comment":
                    state = self._workflow_store.set_comment(tender_id, chat_id, text)
                    self._workflow_waiting.pop(chat_id, None)
                    self._send(chat_id, "✅ Комментарий сохранён.", _keyboard(tender_id, state.status))
                    return
            except Exception:
                logger.exception("Telegram-workflow: ошибка ввода chat_id=%s", chat_id)
                self._send(chat_id, "Не удалось сохранить изменение.", self._keyboard())
                return
        original_message(self, message)

    def handle_callback(self, callback):
        data = str(callback.get("data", ""))
        if not data.startswith("workflow:"):
            original_callback(self, callback)
            return
        message = callback.get("message") or {}
        chat_id = str(message.get("chat", {}).get("id", ""))
        callback_id = str(callback.get("id", ""))
        self._answer_callback(callback_id)
        try:
            parts = data.split(":")
            action = parts[1] if len(parts) > 1 else "show"
            tender_id = int(parts[2]) if len(parts) > 2 else None
            if tender_id is None or not chat_id:
                raise ValueError("Некорректный workflow callback")
            if action == "show":
                _show(self, chat_id, tender_id)
                return
            if action == "history":
                _show_history(self, chat_id, tender_id)
                return
            if action == "tags":
                self._workflow_waiting = getattr(self, "_workflow_waiting", {})
                self._workflow_waiting[chat_id] = (tender_id, "tags")
                self._send(chat_id, "Введите метки через запятую.\n\nНапример: <code>важный, срочно, документы</code>", _back_keyboard(tender_id))
                return
            if action == "comment":
                self._workflow_waiting = getattr(self, "_workflow_waiting", {})
                self._workflow_waiting[chat_id] = (tender_id, "comment")
                self._send(chat_id, "Введите комментарий одним сообщением.", _back_keyboard(tender_id))
                return
            if action == "status" and len(parts) == 4:
                status = parts[3].strip().lower()
                if status not in STATUSES:
                    raise ValueError(f"Неизвестный статус: {status}")
                state = self._workflow_store.set_status(tender_id, chat_id, status)
                self._send(chat_id, f"✅ Статус тендера #{tender_id} изменён на <b>{html.escape(STATUS_NAMES[state.status])}</b>.", _keyboard(tender_id, state.status))
                return
            raise ValueError("Неизвестная workflow операция")
        except Exception:
            logger.exception("Telegram-workflow: ошибка callback=%s chat_id=%s", data, chat_id)
            self._send(chat_id, "Не удалось изменить тендер.", self._keyboard())

    bot_class._handle_callback = handle_callback
    bot_class._handle_message = handle_message
    bot_class._workflow_ui_installed = True
