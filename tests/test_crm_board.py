from datetime import datetime, timedelta, timezone

import pytest

from src.crm.board import TenderBoard
from src.models.tender import Tender
from src.storage.database import TenderDatabase


def make_tender(db, external_id="CRM-1", days=3):
    tender = Tender(
        platform="test",
        external_id=external_id,
        title="Поставка подшипников",
        url=f"https://example.test/{external_id}",
        price=100000,
        deadline=datetime.now(timezone.utc) + timedelta(days=days),
    )
    return db.save_tender(tender)


def test_board_has_safe_status_transitions(tmp_path):
    db = TenderDatabase(tmp_path / "crm.db")
    tender_id = make_tender(db)
    board = TenderBoard(db)

    assert board.status(tender_id) == "new"
    board.set_status(tender_id, "reviewing")
    board.set_status(tender_id, "participating")
    board.set_status(tender_id, "docs_preparation")
    board.set_status(tender_id, "submitted")
    board.set_status(tender_id, "waiting_result")
    board.set_status(tender_id, "won")
    assert board.status(tender_id) == "won"

    with pytest.raises(ValueError):
        board.set_status(tender_id, "submitted")


def test_board_assigns_and_deduplicates_labels(tmp_path):
    db = TenderDatabase(tmp_path / "crm.db")
    tender_id = make_tender(db)
    board = TenderBoard(db)

    board.assign(tender_id, "manager-1")
    board.add_label(tender_id, " Участвуем ")
    board.add_label(tender_id, "участвуем")

    with db._connect() as conn:
        row = conn.execute("SELECT status,assignee_id FROM tender_board WHERE tender_id=?", (tender_id,)).fetchone()
        labels = conn.execute("SELECT label FROM tender_board_labels WHERE tender_id=?", (tender_id,)).fetchall()

    assert row["status"] == "new"
    assert row["assignee_id"] == "manager-1"
    assert [item["label"] for item in labels] == ["Участвуем"]


def test_board_lists_status_and_upcoming_deadlines(tmp_path):
    db = TenderDatabase(tmp_path / "crm.db")
    first = make_tender(db, "CRM-1", days=2)
    second = make_tender(db, "CRM-2", days=20)
    board = TenderBoard(db)
    board.ensure(first)
    board.ensure(second)
    board.set_status(first, "reviewing")
    board.set_status(second, "reviewing")

    assert [row["tender_id"] for row in board.list_by_status("reviewing")] == [first, second]
    assert [row["tender_id"] for row in board.upcoming_deadlines(7)] == [first]


def test_board_history_records_status_changes(tmp_path):
    db = TenderDatabase(tmp_path / "crm.db")
    tender_id = make_tender(db)
    board = TenderBoard(db)
    board.set_status(tender_id, "reviewing")
    board.set_status(tender_id, "participating")

    with db._connect() as conn:
        rows = conn.execute("SELECT old_status,new_status FROM tender_board_history WHERE tender_id=? ORDER BY id", (tender_id,)).fetchall()

    assert [(row["old_status"], row["new_status"]) for row in rows] == [("new", "reviewing"), ("reviewing", "participating")]
