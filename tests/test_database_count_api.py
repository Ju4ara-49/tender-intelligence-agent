from datetime import datetime, timedelta, timezone

from src.models.tender import Tender
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState


def test_count_apis_use_authoritative_storage(tmp_path):
    db = TenderDatabase(tmp_path / "counts.db")
    tender = Tender(
        platform="test",
        external_id="count-1",
        title="Тест",
        url="https://example.test/count-1",
        price=1000,
        deadline=datetime.now(timezone.utc) + timedelta(days=10),
    )
    tender_id = db.save_tender(tender)
    assert db.count_tenders() == 1
    assert db.count_notifications() == 0

    state = NotificationDeliveryState(db)
    assert state.was_notified(tender, recipient_key="user:1") is False
    state.mark_notified(tender, recipient_key="user:1")
    assert db.count_notifications() == 1
    assert db.count_notifications(recipient_key="user:1") == 1
    assert db.count_notifications(recipient_key="user:2") == 0

    assert state.was_notified(tender, recipient_key="user:2") is False
    state.mark_notified(tender, recipient_key="user:2")
    assert db.count_notifications() == 2
    assert db.count_notifications(channel="telegram") == 2
    assert db.count_notifications(channel="email") == 0
    assert db.get_tender_id(tender.unique_key) == tender_id
