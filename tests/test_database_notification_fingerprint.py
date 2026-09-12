from src.models.tender import Tender
from src.storage.database import TenderDatabase


def test_database_notification_fingerprint_uses_normalized_commercial_fields(tmp_path):
    db = TenderDatabase(tmp_path / "notifications.db")
    tender = Tender(
        platform="test",
        external_id="fingerprint-1",
        title="Поставка подшипников",
        url="https://example.test/fingerprint-1",
        price=100000,
        description="Предоплата 30%. Отсрочка платежа 20 календарных дней.",
    )
    tender_id = db.save_tender(tender)

    db.mark_notified(tender_id, recipient_key="chat-a")

    assert db.was_notified(tender.unique_key, recipient_key="chat-a") is True
    assert db.was_notified(tender.unique_key, recipient_key="chat-b") is False
