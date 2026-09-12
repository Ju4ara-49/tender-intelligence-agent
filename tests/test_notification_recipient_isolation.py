from datetime import datetime

from src.models.tender import Tender
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState


def test_notification_delivery_is_isolated_by_recipient(tmp_path) -> None:
    db = TenderDatabase(tmp_path / "notifications.db")
    state = NotificationDeliveryState(db)
    tender = Tender(
        platform="test",
        external_id="1",
        title="Tender",
        url="https://example.test/1",
        price=100,
        deadline=datetime(2030, 1, 1),
    )
    db.save_tender(tender)

    assert state.was_notified(tender, recipient_key="chat-a") is False
    assert state.was_notified(tender, recipient_key="chat-b") is False
    state.mark_notified(tender, recipient_key="chat-a")

    assert state.was_notified(tender, recipient_key="chat-a") is True
    assert state.was_notified(tender, recipient_key="chat-b") is False

    state.mark_notified(tender, recipient_key="chat-b")
    assert state.was_notified(tender, recipient_key="chat-b") is True
