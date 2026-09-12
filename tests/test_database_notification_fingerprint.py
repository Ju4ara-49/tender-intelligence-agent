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


def test_description_change_creates_a_new_notification_event(tmp_path):
    db = TenderDatabase(tmp_path / "description-change.db")
    tender = Tender(
        platform="test",
        external_id="description-change-1",
        title="Поставка подшипников",
        url="https://example.test/description-change-1",
        price=100000,
        description="Поставка в одной партии.",
    )
    tender_id = db.save_tender(tender)
    state = NotificationDeliveryState(db)

    state.mark_notified(tender, recipient_key="chat-a")
    first_key = state.event_key(tender)

    tender.description = "Поставка в двух партиях с изменёнными условиями."
    db.save_tender(tender)
    second_key = state.event_key(tender)

    assert first_key != second_key
    assert state.was_notified(tender, recipient_key="chat-a") is False

    state.mark_notified(tender, recipient_key="chat-a")
    assert state.was_notified(tender, recipient_key="chat-a") is True
    with db._connect() as conn:
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM notification_events
            WHERE tender_id = ? AND recipient_key = ? AND channel = 'telegram'
            """,
            (tender_id, "chat-a"),
        ).fetchone()["count"]
    assert count == 2


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


def test_legacy_repair_preserves_existing_notification_history(tmp_path):
    db = TenderDatabase(tmp_path / "history.db")
    tender = Tender(
        platform="test",
        external_id="history-1",
        title="Поставка подшипников",
        url="https://example.test/history-1",
        price=100000,
    )
    tender_id = db.save_tender(tender)
    db.mark_notified(tender_id)
    first_key = db._current_notification_event_key(tender.unique_key)[1]

    tender.price = 120000
    db.save_tender(tender)
    db.mark_notified(tender_id)
    second_key = db._current_notification_event_key(tender.unique_key)[1]
    assert first_key != second_key

    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO notification_events
                (tender_id, event_key, channel, recipient_key, sent_at, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tender_id, first_key, "telegram", "__legacy__", "2026-01-01T00:00:00+00:00", "{}"),
        )

    NotificationDeliveryState(db)

    with db._connect() as conn:
        events = conn.execute(
            """
            SELECT event_key, recipient_key
            FROM notification_events
            WHERE tender_id = ?
            ORDER BY event_key
            """,
            (tender_id,),
        ).fetchall()

    assert {(row["event_key"], row["recipient_key"]) for row in events} == {
        (first_key, TenderDatabase.DEFAULT_RECIPIENT_KEY),
        (second_key, TenderDatabase.DEFAULT_RECIPIENT_KEY),
    }


def test_notification_events_remain_recipient_specific(tmp_path):
    db = TenderDatabase(tmp_path / "recipients.db")
    tender = Tender(
        platform="test",
        external_id="recipients-1",
        title="Поставка подшипников",
        url="https://example.test/recipients-1",
        price=100000,
    )
    tender_id = db.save_tender(tender)
    state = NotificationDeliveryState(db)

    state.mark_notified(tender, recipient_key="chat-a")

    assert state.was_notified(tender, recipient_key="chat-a") is True
    assert state.was_notified(tender, recipient_key="chat-b") is False
    assert db.count_notifications() == 1

    state.mark_notified(tender, recipient_key="chat-b")

    assert state.was_notified(tender, recipient_key="chat-a") is True
    assert state.was_notified(tender, recipient_key="chat-b") is True
    with db._connect() as conn:
        recipients = conn.execute(
            "SELECT recipient_key FROM notification_events WHERE tender_id = ? ORDER BY recipient_key",
            (tender_id,),
        ).fetchall()
    assert [row["recipient_key"] for row in recipients] == ["chat-a", "chat-b"]
