from datetime import datetime, timedelta, timezone

from src.models.tender import Tender
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState


def _tender(price: float = 1000.0) -> Tender:
    return Tender(
        platform="test",
        external_id="legacy-1",
        title="Тестовый тендер",
        url="https://example.test/legacy-1",
        price=price,
        deadline=datetime.now(timezone.utc) + timedelta(days=10),
    )


def test_legacy_notification_does_not_hide_changed_tender(tmp_path):
    db = TenderDatabase(tmp_path / "legacy.db")
    state = NotificationDeliveryState(db)
    tender = _tender()
    tender_id = db.save_tender(tender)
    state.mark_notified(tender)

    tender.price = 1200.0
    db.save_tender(tender)

    assert state.was_notified(tender) is False
    assert tender_id == db.get_tender_id(tender.unique_key)
