from pathlib import Path

from src.models.tender import Tender
from src.storage.database import TenderDatabase
from src.workflow import STATUSES, TenderWorkflowStore


def make_db(tmp_path: Path) -> tuple[TenderDatabase, int]:
    db = TenderDatabase(tmp_path / "test.db")
    tender = Tender(
        platform="eis", external_id="1", title="Тест", url="https://example.test/1",
        description="", price=1000, currency="RUB",
    )
    return db, db.save_tender(tender)


def test_workflow_isolated_by_user(tmp_path: Path):
    db, tender_id = make_db(tmp_path)
    store = TenderWorkflowStore(db)

    store.set_status(tender_id, "u1", "participate")
    store.set_tags(tender_id, "u1", ["важный", "важный", "срочно"])
    store.set_comment(tender_id, "u1", "Проверить обеспечение")

    assert store.get(tender_id, "u1").status == "participate"
    assert store.get(tender_id, "u1").tags == ["важный", "срочно"]
    assert store.get(tender_id, "u1").comment == "Проверить обеспечение"
    assert store.get(tender_id, "u2").status == "new"
    assert store.get(tender_id, "u2").tags == []


def test_workflow_history_and_status_validation(tmp_path: Path):
    db, tender_id = make_db(tmp_path)
    store = TenderWorkflowStore(db)
    store.set_status(tender_id, "u1", "review")
    store.set_status(tender_id, "u1", "submitted")
    history = store.history(tender_id, "u1")
    assert [item["event_type"] for item in history] == ["status", "status"]
    assert history[-1]["old_value"] == "review"
    assert history[-1]["new_value"] == "submitted"

    for status in STATUSES:
        assert store.set_status(tender_id, "u1", status).status == status

    try:
        store.set_status(tender_id, "u1", "bad-status")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid status must raise ValueError")
