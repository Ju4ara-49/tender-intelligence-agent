from datetime import datetime

from src.models.tender import Tender
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState


def test_recipient_specific_delivery_does_not_become_default_after_restart(tmp_path) -> None:
    db_path = tmp_path / "recipient-boundary.db"
    db = TenderDatabase(db_path)
    tender = Tender(
        platform="test",
        external_id="recipient-boundary",
        title="Tender",
        url="https://example.test/recipient-boundary",
        price=100,
        deadline=datetime(2030, 1, 1),
    )
    db.save_tender(tender)
    state = NotificationDeliveryState(db)
    assert state.was_notified(tender, recipient_key="chat-a") is False
    state.mark_notified(tender, recipient_key="chat-a")

    reopened = TenderDatabase(db_path)
    reopened_state = NotificationDeliveryState(reopened)
    assert reopened_state.was_notified(tender, recipient_key="chat-a") is True
    assert reopened_state.was_notified(tender, recipient_key=NotificationDeliveryState.DEFAULT_RECIPIENT_KEY) is False
