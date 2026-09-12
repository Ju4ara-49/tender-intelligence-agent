from datetime import datetime

from src.models.tender import Tender
from src.storage.database import TenderDatabase


def _tender(raw_data: dict, *, detail_status: str = "partial", detail_diagnostics: str = "") -> Tender:
    return Tender(
        platform="test",
        external_id="history-raw-order",
        title="Tender",
        url="https://example.test/history-raw-order",
        price=100,
        deadline=datetime(2030, 1, 1),
        raw_data=raw_data,
        detail_status=detail_status,
        detail_diagnostics=detail_diagnostics,
    )


def test_reordered_raw_data_keys_do_not_create_false_history_event(tmp_path) -> None:
    db = TenderDatabase(tmp_path / "history.db")
    first = _tender({"alpha": 1, "nested": {"x": 1, "y": 2}})
    tender_id = db.save_tender(first)

    second = _tender({"nested": {"y": 2, "x": 1}, "alpha": 1})
    assert db.save_tender(second) == tender_id

    history = db.get_tender_history(tender_id)
    assert len(history) == 1
    assert history[0]["event_type"] == "created"


def test_detail_status_change_creates_history_event(tmp_path) -> None:
    db = TenderDatabase(tmp_path / "history-status.db")
    tender_id = db.save_tender(_tender({"value": 1}, detail_status="partial"))

    assert db.save_tender(_tender({"value": 1}, detail_status="complete")) == tender_id

    history = db.get_tender_history(tender_id)
    assert len(history) == 2
    assert history[1]["event_type"] == "updated"
    assert history[1]["changed_fields"] == '["detail_status"]'


def test_detail_diagnostics_change_creates_history_event(tmp_path) -> None:
    db = TenderDatabase(tmp_path / "history-diagnostics.db")
    tender_id = db.save_tender(_tender({"value": 1}, detail_diagnostics="first warning"))

    assert db.save_tender(_tender({"value": 1}, detail_diagnostics="second warning")) == tender_id

    history = db.get_tender_history(tender_id)
    assert len(history) == 2
    assert history[1]["changed_fields"] == '["detail_diagnostics"]'
