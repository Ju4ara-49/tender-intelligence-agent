from datetime import datetime, timezone

from src.models.tender import Tender
from src.storage.notification_delivery import NotificationDeliveryState


def make_tender(price=1000000, postpayment=15):
    return Tender(
        platform="rts_tender",
        external_id="42",
        title="Поставка запасных частей",
        url="https://example.test/42",
        price=price,
        start_date=datetime(2026, 9, 12, tzinfo=timezone.utc),
        end_date=datetime(2026, 9, 20, tzinfo=timezone.utc),
        deadline=datetime(2026, 9, 20, tzinfo=timezone.utc),
        published_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        region="Санкт-Петербург",
        customer="ООО Ромашка",
        law_type="223-ФЗ",
        advance_required=True,
        advance_percent=30,
        postpayment_days=postpayment,
        application_security_percent=2,
        contract_security_percent=5,
    )


def test_event_key_changes_when_business_state_changes():
    first = make_tender()
    price_changed = make_tender(price=1200000)
    payment_changed = make_tender(postpayment=30)

    assert NotificationDeliveryState.event_key(first) != NotificationDeliveryState.event_key(price_changed)
    assert NotificationDeliveryState.event_key(first) != NotificationDeliveryState.event_key(payment_changed)
    assert NotificationDeliveryState.event_key(first) == NotificationDeliveryState.event_key(make_tender())
