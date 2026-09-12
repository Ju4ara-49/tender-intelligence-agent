from __future__ import annotations

from datetime import datetime

from src.models.tender import Tender
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState


def test_tender_to_utc_is_idempotent() -> None:
    tender = Tender(
        platform="test",
        external_id="1",
        title="Test",
        url="https://example.test/1",
        deadline=datetime(2026, 9, 12, 12, 0),
    )
    first = tender.deadline
    tender.to_utc()
    assert tender.deadline == first
    assert tender.deadline.tzinfo is not None


def test_tender_detail_contract_defaults() -> None:
    tender = Tender(platform="test", external_id="1", title="Test", url="https://example.test/1")
    assert tender.customer_inn == ""
    assert tender.detail_status == "success"
    assert tender.detail_diagnostics == ""
    assert tender.documents == []


def test_notification_state_is_recipient_aware(tmp_path) -> None:
    db = TenderDatabase(tmp_path / "test.db")
    tender = Tender(platform="test", external_id="1", title="Test", url="https://example.test/1")
    tender_id = db.save_tender(tender)
    state = NotificationDeliveryState(db)

    state.mark_notified(tender, recipient_key="user-a")
    assert state.was_notified(tender, recipient_key="user-a")
    assert not state.was_notified(tender, recipient_key="user-b")

    with db._connect() as conn:
        rows = conn.execute(
            "SELECT recipient_key FROM notification_events WHERE tender_id = ?",
            (tender_id,),
        ).fetchall()
    assert {row["recipient_key"] for row in rows} == {"user-a"}
