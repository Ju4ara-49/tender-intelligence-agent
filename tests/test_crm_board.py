from datetime import datetime, timedelta, timezone

import pytest

from src.crm.board import (
    STATUS_DOCS,
    STATUS_LOST,
    STATUS_NEW,
    STATUS_PARTICIPATING,
    STATUS_REVIEWING,
    STATUS_SKIPPED,
    STATUS_SUBMITTED,
    STATUS_WAITING,
    STATUS_WON,
    InvalidStatusTransition,
    TenderBoard,
)
from src.models.tender import Tender
from src.storage.database import TenderDatabase


def make_tender(db: TenderDatabase, external_id: str = "board-1", **kwargs) -> int:
    tender = Tender(
        platform="test",
        external_id=external_id,
        title="Поставка мебели",
        url=f"https://example.test/{external_id}",
        price=100000,
        **kwargs,
    )
    return db.save_tender(tender)


def test_new_tender_defaults_to_new(tmp_path):
    db = TenderDatabase(tmp_path / "board.db")
    tender_id = make_tender(db)
    board = TenderBoard(db)

    assert board.get_status(tender_id) == STATUS_NEW
    assert board.labels(tender_id) == []
    assert board.entry(tender_id).assignee == ""


def test_allowed_transition_and_history_are_recorded(tmp_path):
    db = TenderDatabase(tmp_path / "board.db")
    tender_id = make_tender(db)
    board = TenderBoard(db)

    board.set_status(tender_id, STATUS_REVIEWING)
    board.set_status(tender_id, STATUS_PARTICIPATING)

    assert board.get_status(tender_id) == STATUS_PARTICIPATING
    assert [x["event_type"] for x in board.history(tender_id)] == ["status_changed", "status_changed"]
    assert board.history(tender_id)[0]["old_value"] == STATUS_NEW


def test_invalid_transition_is_rejected_atomically(tmp_path):
    db = TenderDatabase(tmp_path / "board.db")
    tender_id = make_tender(db)
    board = TenderBoard(db)

    with pytest.raises(InvalidStatusTransition):
        board.set_status(tender_id, STATUS_DOCS)

    assert board.get_status(tender_id) == STATUS_NEW
    assert board.history(tender_id) == []


def test_force_transition_is_allowed(tmp_path):
    db = TenderDatabase(tmp_path / "board.db")
    tender_id = make_tender(db)
    board = TenderBoard(db)

    board.set_status(tender_id, STATUS_DOCS, force=True)

    assert board.get_status(tender_id) == STATUS_DOCS
    assert board.history(tender_id)[0]["old_value"] == STATUS_NEW


def test_assign_preserves_status_and_records_change(tmp_path):
    db = TenderDatabase(tmp_path / "board.db")
    tender_id = make_tender(db)
    board = TenderBoard(db)
    board.set_status(tender_id, STATUS_REVIEWING)

    board.assign(tender_id, "  Иван Петров  ")

    entry = board.entry(tender_id)
    assert entry.assignee == "Иван Петров"
    assert entry.status == STATUS_REVIEWING
    assert board.history(tender_id)[-1]["event_type"] == "assignee_changed"


def test_empty_assignee_is_rejected(tmp_path):
    db = TenderDatabase(tmp_path / "board.db")
    tender_id = make_tender(db)
    board = TenderBoard(db)

    with pytest.raises(ValueError):
        board.assign(tender_id, "   ")


def test_labels_are_case_insensitive_and_removable(tmp_path):
    db = TenderDatabase(tmp_path / "board.db")
    tender_id = make_tender(db)
    board = TenderBoard(db)

    board.add_label(tender_id, " Участвуем ")
    board.add_label(tender_id, "участвуем")
    board.add_label(tender_id, "Юристу")

    assert board.labels(tender_id) == ["Участвуем", "Юристу"]
    board.remove_label(tender_id, " юристу ")
    assert board.labels(tender_id) == ["Участвуем"]
    assert [x["event_type"] for x in board.history(tender_id)] == ["label_added", "label_added", "label_removed"]


def test_list_by_status_includes_implicit_new_tenders(tmp_path):
    db = TenderDatabase(tmp_path / "board.db")
    id_a = make_tender(db, external_id="a")
    id_b = make_tender(db, external_id="b")
    board = TenderBoard(db)

    board.set_status(id_a, STATUS_REVIEWING)

    assert [row["id"] for row in board.list_by_status(STATUS_REVIEWING)] == [id_a]
    assert [row["id"] for row in board.list_by_status(STATUS_NEW)] == [id_b]


def test_upcoming_deadlines_filters_active_status_and_window(tmp_path):
    db = TenderDatabase(tmp_path / "board.db")
    now = datetime.now(timezone.utc)
    soon = now + timedelta(days=1)
    far = now + timedelta(days=30)
    id_soon = make_tender(db, external_id="soon", deadline=soon)
    id_far = make_tender(db, external_id="far", deadline=far)
    id_skipped = make_tender(db, external_id="skipped", deadline=soon)

    board = TenderBoard(db)
    board.set_status(id_soon, STATUS_REVIEWING)
    board.set_status(id_far, STATUS_REVIEWING)
    board.set_status(id_skipped, STATUS_SKIPPED, force=True)

    assert [row["id"] for row in board.upcoming_deadlines(3)] == [id_soon]
    assert board.upcoming_deadlines(0) == []


def test_upcoming_deadlines_rejects_invalid_window(tmp_path):
    db = TenderDatabase(tmp_path / "board.db")
    TenderBoard(db)

    with pytest.raises(ValueError):
        TenderBoard(db).upcoming_deadlines(-1)
    with pytest.raises(TypeError):
        TenderBoard(db).upcoming_deadlines(1.5)


def test_terminal_and_reopen_transitions(tmp_path):
    db = TenderDatabase(tmp_path / "board.db")
    tender_id = make_tender(db)
    board = TenderBoard(db)

    for status in (STATUS_REVIEWING, STATUS_PARTICIPATING, STATUS_DOCS, STATUS_SUBMITTED, STATUS_WAITING, STATUS_LOST):
        board.set_status(tender_id, status)
    board.set_status(tender_id, STATUS_REVIEWING)
    board.set_status(tender_id, STATUS_PARTICIPATING)
    board.set_status(tender_id, STATUS_DOCS)
    board.set_status(tender_id, STATUS_SUBMITTED)
    board.set_status(tender_id, STATUS_WAITING)
    board.set_status(tender_id, STATUS_WON, force=True)

    assert board.get_status(tender_id) == STATUS_WON
    with pytest.raises(InvalidStatusTransition):
        board.set_status(tender_id, STATUS_REVIEWING)
