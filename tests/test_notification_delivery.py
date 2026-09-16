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


def test_rich_delivery_state_detects_payment_and_security_changes(tmp_path):
    db = TenderDatabase(tmp_path / "rich.db")
    state = NotificationDeliveryState(db)
    tender = _tender()
    tender.postpayment_days = 30
    tender.advance_required = True
    tender.advance_percent = 20.0
    tender.application_security_percent = 1.0
    tender.contract_security_percent = 5.0
    db.save_tender(tender)
    state.mark_notified(tender)

    tender.postpayment_days = 45
    tender.advance_percent = 30.0
    tender.application_security_percent = 2.0
    tender.contract_security_percent = 10.0
    db.save_tender(tender)

    assert state.was_notified(tender) is False


def test_rich_delivery_state_accepts_identical_state(tmp_path):
    db = TenderDatabase(tmp_path / "same.db")
    state = NotificationDeliveryState(db)
    tender = _tender()
    db.save_tender(tender)
    state.mark_notified(tender)

    assert state.was_notified(tender) is True
    assert db.count_notifications() == 1


def test_notification_state_detects_description_change(tmp_path):
    db = TenderDatabase(tmp_path / "description.db")
    state = NotificationDeliveryState(db)
    tender = _tender()
    tender.description = "Поставка запасных частей"
    db.save_tender(tender)
    state.mark_notified(tender)

    tender.description = "Поставка запасных частей и комплектующих"
    db.save_tender(tender)

    assert state.was_notified(tender) is False
