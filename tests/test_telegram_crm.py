from __future__ import annotations

import tempfile
from pathlib import Path

from src.crm.telegram import handle_callback, handle_message
from src.storage.database import TenderDatabase


class _Orchestrator:
    def __init__(self, db):
        self.db = db


class _Bot:
    def __init__(self, db):
        self.orchestrator = _Orchestrator(db)
        self.sent = []
        self.crm_board = None

    @staticmethod
    def _keyboard():
        return {"keyboard": []}

    def _send(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))
        return None


def _db_with_tender() -> TenderDatabase:
    db = TenderDatabase(Path(tempfile.mkdtemp()) / "test.db")
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO tenders (
                platform, external_id, unique_key, title, url,
                first_seen_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "eis",
                "T-1",
                "eis:T-1",
                "Тестовый тендер",
                "https://example.test/tender/1",
                "2026-09-13T00:00:00+00:00",
                "2026-09-13T00:00:00+00:00",
            ),
        )
    return db


def test_tender_card_command_and_status_button():
    db = _db_with_tender()
    bot = _Bot(db)

    assert handle_message(bot, "42", "/tender 1") is True
    assert "CRM тендера #1" in bot.sent[-1][1]
    keyboard = bot.sent[-1][2]
    assert any(
        button["callback_data"] == "crm:status:1:reviewing"
        for row in keyboard["inline_keyboard"]
        for button in row
    )
    assert not any(
        button["callback_data"] == "crm:status:1:won"
        for row in keyboard["inline_keyboard"]
        for button in row
    )

    assert handle_callback(bot, "42", "crm:status:1:reviewing") is True
    assert "Проверить" in bot.sent[-1][1]
    assert bot.crm_board.get_status(1) == "reviewing"


def test_crm_status_accepts_russian_label():
    db = _db_with_tender()
    bot = _Bot(db)

    assert handle_message(bot, "42", "/crm_status 1 Проверить") is True
    assert bot.crm_board.get_status(1) == "reviewing"
    assert "Проверить" in bot.sent[-1][1]


def test_crm_assignment_and_label_commands_are_persisted():
    db = _db_with_tender()
    bot = _Bot(db)

    assert handle_message(bot, "42", "/assign 1 Иван Петров") is True
    assert handle_message(bot, "42", "/label 1 Юристу") is True

    entry = bot.crm_board.entry(1)
    assert entry.assignee == "Иван Петров"
    assert entry.labels == ["Юристу"]


def test_crm_commands_validate_tender_id_and_unknown_tender():
    db = _db_with_tender()
    bot = _Bot(db)

    assert handle_message(bot, "42", "/tender nope") is True
    assert "положительным целым" in bot.sent[-1][1]

    assert handle_message(bot, "42", "/tender 999") is True
    assert "Tender not found" in bot.sent[-1][1]


def test_telegram_crm_state_isolated_by_chat_id():
    db = _db_with_tender()
    bot = _Bot(db)

    assert handle_message(bot, "42", "/crm_status 1 Проверить") is True
    assert bot.crm_board.get_status(1) == "reviewing"

    assert handle_message(bot, "43", "/tender 1") is True
    assert "Новый" in bot.sent[-1][1]

    assert handle_callback(bot, "43", "crm:status:1:reviewing") is True
    assert handle_callback(bot, "43", "crm:status:1:participating") is True
    assert bot.crm_board.get_status(1) == "reviewing"
    assert bot.crm_boards["43"].get_status(1) == "participating"
