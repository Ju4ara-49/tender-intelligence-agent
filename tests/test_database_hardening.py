from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from src.models.tender import Tender
from src.storage import (
    InvalidStatusTransition,
    STATUS_DOCS,
    STATUS_LOST,
    STATUS_PARTICIPATING,
    STATUS_REVIEWING,
    STATUS_SKIPPED,
    STATUS_SUBMITTED,
    STATUS_WAITING,
    STATUS_WON,
    TenderBoard,
)
from src.storage.database import TenderDatabase


_FIXED_DEADLINE = datetime(2030, 1, 20, 12, 0, tzinfo=timezone.utc)


def _tender(
    price: float = 100.0,
    title: str = "Подшипник",
    deadline: datetime = _FIXED_DEADLINE,
    external_id: str = "123",
) -> Tender:
    return Tender(
        platform="eis",
        external_id=external_id,
        title=title,
        url=f"https://example.test/tender/{external_id}",
        description="Тестовый тендер",
        price=price,
        deadline=deadline,
        region="Москва",
        customer="Тестовый заказчик",
        raw_data={"details": {"price": price}},
    )


def test_search_numbers_are_unique_under_concurrency(tmp_path):
    db = TenderDatabase(tmp_path / "test.sqlite3")
    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(lambda _: db.next_search_number(), range(40)))
    assert sorted(numbers) == list(range(1, 41))


def test_tender_history_records_creation_and_real_change(tmp_path):
    db = TenderDatabase(tmp_path / "test.sqlite3")
    tender_id = db.save_tender(_tender(price=100.0))
    history = db.get_tender_history(tender_id)
    assert len(history) == 1
    assert history[0]["event_type"] == "created"

    db.save_tender(_tender(price=100.0))
    assert len(db.get_tender_history(tender_id)) == 1

    db.save_tender(_tender(price=125.0, title="Изменённый подшипник"))
    history = db.get_tender_history(tender_id)
    assert len(history) == 2
    assert history[-1]["event_type"] == "updated"
    assert "price" in history[-1]["changed_fields"]
    assert "title" in history[-1]["changed_fields"]


def test_sqlite_wal_and_busy_timeout_are_enabled(tmp_path):
    db = TenderDatabase(tmp_path / "test.sqlite3")
    with db._connect() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert str(journal_mode).lower() == "wal"
    assert busy_timeout >= 10000


def test_crm_board_defaults_to_new_and_persists_status(tmp_path):
    db = TenderDatabase(tmp_path / "crm.sqlite3")
    tender_id = db.save_tender(_tender())
    board = TenderBoard(db)
    assert board.get_status(tender_id) == "new"
    assert board.set_status(tender_id, STATUS_REVIEWING) == STATUS_REVIEWING
    assert board.get_status(tender_id) == STATUS_REVIEWING


def test_crm_board_rejects_invalid_transition_and_supports_force(tmp_path):
    db = TenderDatabase(tmp_path / "crm.sqlite3")
    tender_id = db.save_tender(_tender())
    board = TenderBoard(db)
    with pytest.raises(InvalidStatusTransition):
        board.set_status(tender_id, STATUS_WON)
    assert board.set_status(tender_id, STATUS_WON, force=True) == STATUS_WON


def test_crm_board_full_workflow_and_terminal_states(tmp_path):
    db = TenderDatabase(tmp_path / "crm.sqlite3")
    tender_id = db.save_tender(_tender(external_id="workflow-win"))
    board = TenderBoard(db)
    for status in (STATUS_REVIEWING, STATUS_PARTICIPATING, STATUS_DOCS, STATUS_SUBMITTED, STATUS_WAITING, STATUS_WON):
        assert board.set_status(tender_id, status) == status
    assert board.get_status(tender_id) == STATUS_WON
    with pytest.raises(InvalidStatusTransition):
        board.set_status(tender_id, STATUS_REVIEWING)

    tender2 = db.save_tender(_tender(title="Проигрыш", external_id="workflow-loss"))
    for status in (STATUS_REVIEWING, STATUS_PARTICIPATING, STATUS_DOCS, STATUS_SUBMITTED, STATUS_WAITING):
        board.set_status(tender2, status)
    board.set_status(tender2, STATUS_LOST)
    assert board.set_status(tender2, STATUS_REVIEWING) == STATUS_REVIEWING

    tender3 = db.save_tender(_tender(title="Пропуск", external_id="workflow-skip"))
    assert board.set_status(tender3, STATUS_SKIPPED) == STATUS_SKIPPED
    assert board.set_status(tender3, STATUS_REVIEWING) == STATUS_REVIEWING


def test_crm_board_assignment_and_labels_are_idempotent(tmp_path):
    db = TenderDatabase(tmp_path / "crm.sqlite3")
    tender_id = db.save_tender(_tender())
    board = TenderBoard(db)
    board.assign(tender_id, "  Иван  ")
    board.add_label(tender_id, " Юристу ")
    board.add_label(tender_id, "Юристу")
    board.add_label(tender_id, "Участвуем")
    entry = board.entry(tender_id)
    assert entry.assignee == "Иван"
    assert entry.labels == ["Участвуем", "Юристу"]
    board.remove_label(tender_id, "Юристу")
    assert board.labels(tender_id) == ["Участвуем"]


def test_crm_board_list_by_status_includes_implicit_new_tenders(tmp_path):
    db = TenderDatabase(tmp_path / "crm.sqlite3")
    first = db.save_tender(_tender(title="Ранний", deadline=_FIXED_DEADLINE, external_id="list-new"))
    second = db.save_tender(_tender(title="Поздний", deadline=_FIXED_DEADLINE + timedelta(days=1), external_id="list-review"))
    board = TenderBoard(db)
    board.set_status(second, STATUS_REVIEWING)
    assert [row["id"] for row in board.list_by_status("new")] == [first]
    assert board.list_by_status(STATUS_REVIEWING)[0]["id"] == second


def test_crm_board_upcoming_deadlines_filters_active_window(tmp_path):
    db = TenderDatabase(tmp_path / "crm.sqlite3")
    now = datetime.now(timezone.utc)
    due = db.save_tender(_tender(title="Скоро", deadline=now + timedelta(days=1), external_id="due"))
    far = db.save_tender(_tender(title="Позже", deadline=now + timedelta(days=10), external_id="far"))
    new_tender = db.save_tender(_tender(title="Новый", deadline=now + timedelta(days=1), external_id="new"))
    board = TenderBoard(db)
    board.set_status(due, STATUS_REVIEWING)
    board.set_status(far, STATUS_REVIEWING)
    rows = board.upcoming_deadlines(3)
    assert [row["id"] for row in rows] == [due]
    assert new_tender not in [row["id"] for row in rows]


def test_crm_board_rejects_unknown_status_and_invalid_deadline_window(tmp_path):
    db = TenderDatabase(tmp_path / "crm.sqlite3")
    tender_id = db.save_tender(_tender())
    board = TenderBoard(db)
    with pytest.raises(ValueError):
        board.set_status(tender_id, "broken")
    with pytest.raises(ValueError):
        board.upcoming_deadlines(-1)
