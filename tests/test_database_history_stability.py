from datetime import datetime

from src.models.tender import Tender
from src.storage.database import TenderDatabase


def _tender(raw_data: dict) -> Tender:
    return Tender(
        platform="test",
        external_id="history-raw-order",
        title="Tender",
        url="https://example.test/history-raw-order",
        price=100,
        deadline=datetime(2030, 1, 1),
        raw_data=raw_data,
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
