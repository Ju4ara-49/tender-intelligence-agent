from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.models.tender import Tender
from src.storage import (
    STATUS_ARCHIVED,
    STATUS_EXPIRED,
    STATUS_LOST,
    STATUS_WON,
    TenderBoard,
)
from src.storage.database import TenderDatabase


def _db(tmp_path: Path) -> tuple[TenderDatabase, TenderBoard, int]:
    db = TenderDatabase(tmp_path / "agent.db")
    tender = Tender(
        platform="test",
        external_id="1",
        title="Expired tender",
        url="https://example.test/1",
        deadline=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.save_tender(tender)
    tender_id = db.get_tender_id(tender.unique_key)
    assert tender_id is not None
    return db, TenderBoard(db), tender_id


def test_expire_overdue_moves_only_open_pre_submission_cards(tmp_path: Path):
    db, board, tender_id = _db(tmp_path)
    assert board.get_status(tender_id) == "new"
    assert board.expire_overdue() == [tender_id]
    assert board.get_status(tender_id) == STATUS_EXPIRED


def test_archive_accepts_terminal_states_only(tmp_path: Path):
    db, board, tender_id = _db(tmp_path)
    board.set_status(tender_id, STATUS_EXPIRED)
    assert board.archive(tender_id) == STATUS_ARCHIVED
    assert board.get_status(tender_id) == STATUS_ARCHIVED
