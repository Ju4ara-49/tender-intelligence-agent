from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.storage import (
    STATUS_DOCS,
    STATUS_LOST,
    STATUS_NEW,
    STATUS_PARTICIPATING,
    STATUS_REVIEWING,
    STATUS_WON,
    InvalidStatusTransition,
    TenderBoard,
)
from src.storage.database import TenderDatabase


def _db_with_tender(deadline: str | None = None) -> TenderDatabase:
    db = TenderDatabase(Path(tempfile.mkdtemp()) / "crm.db")
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO tenders (
                platform, external_id, unique_key, title, url, deadline,
                first_seen_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("eis", "CRM-1", "eis:CRM-1", "CRM тест", "https://example.test/1", deadline,
             "2026-09-13T00:00:00+00:00", "2026-09-13T00:00:00+00:00"),
        )
    return db


def test_new_tender_defaults_to_new_and_validates_transitions():
    board = TenderBoard(_db_with_tender())
    assert board.get_status(1) == STATUS_NEW
    assert board.set_status(1, STATUS_REVIEWING) == STATUS_REVIEWING
    assert board.set_status(1, STATUS_PARTICIPATING) == STATUS_PARTICIPATING
    assert board.set_status(1, STATUS_DOCS) == STATUS_DOCS
    with pytest.raises(InvalidStatusTransition):
        board.set_status(1, STATUS_WON)


def test_force_transition_and_terminal_return_path():
    board = TenderBoard(_db_with_tender())
    board.set_status(1, STATUS_WON, force=True)
    assert board.get_status(1) == STATUS_WON
    with pytest.raises(InvalidStatusTransition):
        board.set_status(1, STATUS_REVIEWING)

    board.set_status(1, STATUS_LOST, force=True)
    assert board.set_status(1, STATUS_REVIEWING) == STATUS_REVIEWING


def test_assignment_and_labels_are_idempotent():
    board = TenderBoard(_db_with_tender())
    board.assign(1, " Иван Петров ")
    board.add_label(1, "Юристу")
    board.add_label(1, "Юристу")
    board.add_label(1, "Участвуем")

    entry = board.entry(1)
    assert entry.assignee == "Иван Петров"
    assert entry.labels == ["Участвуем", "Юристу"]

    board.remove_label(1, "Юристу")
    assert board.labels(1) == ["Участвуем"]


def test_invalid_tender_is_rejected_before_writing():
    board = TenderBoard(_db_with_tender())
    with pytest.raises(ValueError, match="Tender not found"):
        board.assign(999, "Иван")
    with pytest.raises(ValueError, match="Invalid tender_id"):
        board.get_status(0)


def test_list_by_status_includes_unassigned_new_tenders():
    board = TenderBoard(_db_with_tender())
    rows = board.list_by_status(STATUS_NEW)
    assert [row["id"] for row in rows] == [1]
    assert rows[0]["labels"] == []


def test_upcoming_deadlines_returns_only_active_board_entries():
    soon = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    board = TenderBoard(_db_with_tender(soon))
    assert board.upcoming_deadlines(3) == []
    board.set_status(1, STATUS_REVIEWING)
    rows = board.upcoming_deadlines(3)
    assert len(rows) == 1
    assert rows[0]["id"] == 1
    assert rows[0]["status"] == STATUS_REVIEWING


def test_negative_deadline_window_is_rejected():
    board = TenderBoard(_db_with_tender())
    with pytest.raises(ValueError, match="within_days"):
        board.upcoming_deadlines(-1)
