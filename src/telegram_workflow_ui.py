"""Telegram UI для управления статусом тендера пользователем."""
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
    return {"inline_keyboard": rows}


def _show(bot, chat_id: str, tender_id: int) -> None:
    workflow = bot._workflow_store.get(tender_id, chat_id)
    bot._send(
        chat_id,
        f"<b>Статус тендера #{tender_id}</b>\n\n"
        f"Текущий статус: <b>{html.escape(STATUS_NAMES.get(workflow.status, workflow.status))}</b>",
        _keyboard(tender_id, workflow.status),
    )


def install(bot_class) -> None:
    """Перехватить только callback_data вида workflow:* и оставить остальные UI нетронутыми."""
    if getattr(bot_class, "_workflow_ui_installed", False):
        return
    original_callback = bot_class._handle_callback

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
            if action == "status" and len(parts) == 4:
                status = parts[3].strip().lower()
                if status not in STATUSES:
                    raise ValueError(f"Неизвестный статус: {status}")
                state = self._workflow_store.set_status(tender_id, chat_id, status)
                self._send(
                    chat_id,
                    f"✅ Статус тендера #{tender_id} изменён на <b>{html.escape(STATUS_NAMES[state.status])}</b>.",
                    _keyboard(tender_id, state.status),
                )
                return
            raise ValueError("Неизвестная workflow операция")
        except Exception:
            logger.exception("Telegram-workflow: ошибка callback=%s chat_id=%s", data, chat_id)
            self._send(chat_id, "Не удалось изменить статус тендера.", self._keyboard())

    bot_class._handle_callback = handle_callback
    bot_class._workflow_ui_installed = True
