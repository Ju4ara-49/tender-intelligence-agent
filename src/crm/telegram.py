"""Telegram-команды для CRM-доски тендеров.

Модуль намеренно отделён от polling-кода: он получает объект бота и использует
только его публичные для транспорта методы ``_send``/``_keyboard``. Это позволяет
тестировать CRM-команды без сети Telegram.
"""
from __future__ import annotations

import html
import re
from typing import Any

from src.crm import ALL_STATUSES, TenderBoard
from src.storage import ALLOWED_TRANSITIONS

_STATUS_NAMES = {
    "new": "Новый",
    "reviewing": "Проверить",
    "participating": "Участвуем",
    "docs_preparation": "Документы",
    "submitted": "Подано",
    "waiting_result": "Ожидание результата",
    "won": "Победа",
    "lost": "Проигрыш",
    "skipped": "Пропускаем",
    "expired": "Просрочен",
    "archived": "В архиве",
}
_STATUS_COMMANDS = {name.casefold(): key for key, name in _STATUS_NAMES.items()}
_ID_RE = re.compile(r"^[1-9]\d*$")


def _board(bot: Any) -> TenderBoard:
    board = getattr(bot, "crm_board", None)
    if board is None:
        board = TenderBoard(bot.orchestrator.db)
        bot.crm_board = board
    return board


def _parse_id(value: str) -> int | None:
    return int(value) if _ID_RE.fullmatch(value) else None


def _parse_status(value: str) -> str | None:
    normalized = value.strip().casefold()
    if normalized in ALL_STATUSES:
        return normalized
    return _STATUS_COMMANDS.get(normalized)


def _status_keyboard(tender_id: int, current: str) -> dict:
    """Show only valid transitions, in the stable CRM status order."""
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    rows = [
        [{"text": _STATUS_NAMES[status], "callback_data": f"crm:status:{tender_id}:{status}"}]
        for status in ALL_STATUSES
        if status in allowed
    ]
    return {"inline_keyboard": rows}


def _render_entry(bot: Any, tender_id: int) -> str:
    entry = _board(bot).entry(tender_id)
    return (
        f"<b>CRM тендера #{entry.tender_id}</b>\n\n"
        f"Статус: <b>{html.escape(_STATUS_NAMES.get(entry.status, entry.status))}</b>\n"
        f"Ответственный: {html.escape(entry.assignee or 'не назначен')}\n"
        f"Метки: {html.escape(', '.join(entry.labels) if entry.labels else 'нет')}\n"
        f"Обновлено: {html.escape(entry.updated_at or 'ещё не изменялся')}"
    )


def handle_message(bot: Any, chat_id: str, text: str) -> bool:
    """Обработать CRM-команду. Возвращает True, если команда распознана."""
    parts = text.split(maxsplit=2)
    command = parts[0].lower() if parts else ""

    if command == "/status" and len(parts) == 1:
        bot._cmd_status(chat_id)
        return True

    if command in {"/tender", "/crm"}:
        if len(parts) != 2:
            bot._send(chat_id, "Использование: <code>/tender ID</code>", bot._keyboard())
            return True
        tender_id = _parse_id(parts[1])
        if tender_id is None:
            bot._send(chat_id, "ID тендера должен быть положительным целым числом.", bot._keyboard())
            return True
        try:
            board = _board(bot)
            entry = board.entry(tender_id)
            bot._send(chat_id, _render_entry(bot, tender_id), _status_keyboard(tender_id, entry.status))
        except ValueError as exc:
            bot._send(chat_id, html.escape(str(exc)), bot._keyboard())
        return True

    if command in {"/crm_status", "/статус_тендера"}:
        if len(parts) != 3:
            bot._send(chat_id, "Использование: <code>/crm_status ID STATUS</code>\n\nСтатусы: " + ", ".join(_STATUS_NAMES.values()), bot._keyboard())
            return True
        tender_id = _parse_id(parts[1])
        status = _parse_status(parts[2])
        if tender_id is None or status is None:
            bot._send(chat_id, "Некорректный ID или статус.", bot._keyboard())
            return True
        try:
            new_status = _board(bot).set_status(tender_id, status)
            bot._send(chat_id, f"Статус тендера #{tender_id}: <b>{html.escape(_STATUS_NAMES[new_status])}</b>", bot._keyboard())
        except (ValueError, TypeError) as exc:
            bot._send(chat_id, html.escape(str(exc)), bot._keyboard())
        return True

    if command in {"/assign", "/ответственный"}:
        if len(parts) != 3:
            bot._send(chat_id, "Использование: <code>/assign ID ФИО</code>", bot._keyboard())
            return True
        tender_id = _parse_id(parts[1])
        assignee = parts[2].strip()
        if tender_id is None or not assignee:
            bot._send(chat_id, "Некорректный ID или ответственный.", bot._keyboard())
            return True
        try:
            _board(bot).assign(tender_id, assignee)
            bot._send(chat_id, f"Ответственный для #{tender_id} назначен: <b>{html.escape(assignee)}</b>", bot._keyboard())
        except (ValueError, TypeError) as exc:
            bot._send(chat_id, html.escape(str(exc)), bot._keyboard())
        return True

    if command in {"/label", "/метка"}:
        if len(parts) != 3:
            bot._send(chat_id, "Использование: <code>/label ID метка</code>", bot._keyboard())
            return True
        tender_id = _parse_id(parts[1])
        label = parts[2].strip()
        if tender_id is None or not label:
            bot._send(chat_id, "Некорректный ID или метка.", bot._keyboard())
            return True
        try:
            _board(bot).add_label(tender_id, label)
            bot._send(chat_id, f"Метка добавлена к тендеру #{tender_id}: <b>{html.escape(label)}</b>", bot._keyboard())
        except (ValueError, TypeError) as exc:
            bot._send(chat_id, html.escape(str(exc)), bot._keyboard())
        return True

    return False


def handle_callback(bot: Any, chat_id: str, data: str) -> bool:
    """Обработать inline-кнопки CRM."""
    if data.startswith("crm:participate:"):
        payload = data[len("crm:participate:"):]
        if ":" not in payload:
            return False
        platform, external_id = payload.split(":", 1)
        platform = platform.strip()
        external_id = external_id.strip()
        if not platform or not external_id:
            return False
        unique_key = f"{platform}:{external_id}"
        tender_id = bot.orchestrator.db.get_tender_id(unique_key)
        if tender_id is None:
            bot._send(chat_id, "Не удалось найти тендер в базе для изменения CRM-статуса.", bot._keyboard())
            return True
        try:
            # The button is an explicit user command to participate. It is
            # intentionally allowed to jump from the initial "new" state.
            new_status = _board(bot).set_status(tender_id, "participating", force=True)
            bot._send(chat_id, f"Статус тендера #{tender_id} изменён на <b>{html.escape(_STATUS_NAMES[new_status])}</b>.", bot._keyboard())
        except (ValueError, TypeError) as exc:
            bot._send(chat_id, html.escape(str(exc)), bot._keyboard())
        return True

    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "crm" or parts[1] != "status":
        return False
    tender_id = _parse_id(parts[2])
    status = _parse_status(parts[3])
    if tender_id is None or status is None:
        return False
    try:
        new_status = _board(bot).set_status(tender_id, status)
        bot._send(chat_id, f"Статус тендера #{tender_id} изменён на <b>{html.escape(_STATUS_NAMES[new_status])}</b>.", bot._keyboard())
    except (ValueError, TypeError) as exc:
        bot._send(chat_id, html.escape(str(exc)), bot._keyboard())
    return True
