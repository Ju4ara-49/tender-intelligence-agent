from src.models.tender import Tender
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState


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


def test_legacy_notification_recipient_is_removed_after_repair(tmp_path):
    db = TenderDatabase(tmp_path / "legacy.db")
    tender = Tender(
        platform="test",
        external_id="legacy-1",
        title="Поставка подшипников",
        url="https://example.test/legacy-1",
        price=100000,
    )
    tender_id = db.save_tender(tender)
    db.mark_notified(tender_id)

    with db._connect() as conn:
        row = conn.execute(
            "SELECT event_key, channel, sent_at, payload FROM notification_events WHERE tender_id = ? LIMIT 1",
            (tender_id,),
        ).fetchone()
        conn.execute("DELETE FROM notification_events WHERE tender_id = ?", (tender_id,))
        conn.execute(
            """
            INSERT INTO notification_events
                (tender_id, event_key, channel, recipient_key, sent_at, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tender_id, row["event_key"], row["channel"], "__legacy__", row["sent_at"], row["payload"]),
        )

    repaired = NotificationDeliveryState(db)

    assert repaired.was_notified(tender) is True
    with db._connect() as conn:
        recipients = conn.execute(
            "SELECT recipient_key FROM notification_events WHERE tender_id = ?",
            (tender_id,),
        ).fetchall()

    assert [item["recipient_key"] for item in recipients] == [TenderDatabase.DEFAULT_RECIPIENT_KEY]
