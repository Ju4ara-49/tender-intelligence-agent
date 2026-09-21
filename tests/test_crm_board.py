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


def test_labels_are_case_insensitive_but_keep_first_display_spelling():
    board = TenderBoard(_db_with_tender())
    board.add_label(1, " Участвуем ")
    board.add_label(1, "участвуем")
    assert board.labels(1) == ["Участвуем"]
    board.remove_label(1, " УЧАСТВУЕМ ")
    assert board.labels(1) == []


def test_crm_history_records_status_assignee_and_label_changes():
    board = TenderBoard(_db_with_tender())
    board.set_status(1, STATUS_REVIEWING)
    board.assign(1, "Иван")
    board.add_label(1, "Юристу")
    board.remove_label(1, "юристу")
    board.unassign(1)

    events = board.history(1)
    assert [event["event_type"] for event in events] == [
        "status_changed",
        "assignee_changed",
        "label_added",
        "label_removed",
        "assignee_changed",
    ]
    assert events[0]["old_value"] == "new"
    assert events[0]["new_value"] == "reviewing"
    assert events[1]["old_value"] == ""
    assert events[1]["new_value"] == "Иван"
    assert events[2]["new_value"] == "Юристу"
    assert events[3]["old_value"] == "Юристу"
    assert events[4]["old_value"] == "Иван"
    assert events[4]["new_value"] == ""


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



def test_storage_and_crm_imports_share_one_canonical_board():
    from src.crm.board import TenderBoard as CrmTenderBoard
    from src.storage import TenderBoard as StorageTenderBoard
    assert CrmTenderBoard is StorageTenderBoard


def test_legacy_label_schema_is_migrated_without_case_duplicates(tmp_path):
    db = TenderDatabase(tmp_path / "legacy_crm.db")
    with db._connect() as conn:
        conn.execute("INSERT INTO tenders (platform, external_id, unique_key, title, url, first_seen_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", ("eis", "LEGACY-1", "eis:LEGACY-1", "Legacy CRM", "https://example.test/legacy", "2026-09-14T00:00:00+00:00", "2026-09-14T00:00:00+00:00"))
        conn.execute("CREATE TABLE tender_board (tender_id INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'new', assignee TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)")
        conn.execute("CREATE TABLE tender_labels (id INTEGER PRIMARY KEY AUTOINCREMENT, tender_id INTEGER NOT NULL, label TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(tender_id, label))")
        conn.execute("INSERT INTO tender_labels (tender_id, label, created_at) VALUES (1, ' Участвуем ', '2026-09-14T00:00:00+00:00')")
        conn.execute("INSERT INTO tender_labels (tender_id, label, created_at) VALUES (1, 'участвуем', '2026-09-14T00:00:01+00:00')")
    board = TenderBoard(db)
    assert board.labels(1) == ["Участвуем"]
    board.add_label(1, "УЧАСТВУЕМ")
    assert board.labels(1) == ["Участвуем"]


def test_crm_board_isolates_status_assignment_and_labels_between_users():
    db = _db_with_tender()
    first = TenderBoard(db, user_id="user-a")
    second = TenderBoard(db, user_id="user-b")

    first.set_status(1, STATUS_REVIEWING)
    first.assign(1, "Иван")
    first.add_label(1, "Юристу")

    assert first.get_status(1) == STATUS_REVIEWING
    assert first.entry(1).assignee == "Иван"
    assert first.labels(1) == ["Юристу"]

    assert second.get_status(1) == STATUS_NEW
    assert second.entry(1).assignee == ""
    assert second.labels(1) == []

    second.set_status(1, STATUS_PARTICIPATING)
    second.add_label(1, "Закупки")

    assert first.get_status(1) == STATUS_REVIEWING
    assert first.labels(1) == ["Юристу"]
    assert second.get_status(1) == STATUS_PARTICIPATING
    assert second.labels(1) == ["Закупки"]


def test_scoped_crm_history_isolated_by_user():
    db = _db_with_tender()
    first = TenderBoard(db, user_id="user-a")
    second = TenderBoard(db, user_id="user-b")

    first.set_status(1, STATUS_REVIEWING)
    second.set_status(1, STATUS_REVIEWING)

    assert len(first.history(1)) == 1
    assert len(second.history(1)) == 1
    assert first.history(1)[0]["new_value"] == STATUS_REVIEWING
    assert second.history(1)[0]["new_value"] == STATUS_REVIEWING
