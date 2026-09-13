from datetime import datetime, timezone

from src.models.tender import Tender
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState


def _tender() -> Tender:
    return Tender(
        platform="eis",
        external_id="migration-1",
        title="Migration tender",
        url="https://example.test/migration-1",
        price=100.0,
        deadline=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


def test_legacy_notification_is_migrated_idempotently_to_default_recipient(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    db = TenderDatabase(db_path)
    tender = _tender()
    db.save_tender(tender)
    tender_id = db.get_tender_id(tender.unique_key)
    assert tender_id is not None

    with db._connect() as conn:
        conn.execute(
            "INSERT INTO notifications (tender_id, channel, sent_at, payload) VALUES (?, ?, ?, ?)",
            (tender_id, "telegram", "2030-01-01T00:00:00+00:00", "{\"legacy\":true}"),
        )

    reopened = TenderDatabase(db_path)
    assert reopened.was_notified(tender.unique_key) is True

    with reopened._connect() as conn:
        rows = conn.execute(
            "SELECT recipient_key, COUNT(*) AS count FROM notification_events GROUP BY recipient_key"
        ).fetchall()
    assert [(row["recipient_key"], row["count"]) for row in rows] == [("__default__", 1)]

    reopened_again = TenderDatabase(db_path)
    with reopened_again._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM notification_events").fetchone()[0]
    assert count == 1


def test_recipient_specific_delivery_never_populates_legacy_default_record(tmp_path):
    db_path = tmp_path / "recipient.sqlite3"
    db = TenderDatabase(db_path)
    tender = _tender()
    db.save_tender(tender)

    state = NotificationDeliveryState(db)
    assert state.was_notified(tender, recipient_key="chat-a") is False
    state.mark_notified(tender, recipient_key="chat-a")

    with db._connect() as conn:
        legacy = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE tender_id = (SELECT id FROM tenders WHERE unique_key = ?)",
            (tender.unique_key,),
        ).fetchone()[0]
        default_events = conn.execute(
            "SELECT COUNT(*) FROM notification_events WHERE recipient_key = '__default__'"
        ).fetchone()[0]
        recipient_events = conn.execute(
            "SELECT COUNT(*) FROM notification_events WHERE recipient_key = 'chat-a'"
        ).fetchone()[0]

    assert legacy == 0
    assert default_events == 0
    assert recipient_events == 1


def test_notification_event_migration_preserves_existing_legacy_recipient_key(tmp_path):
    db_path = tmp_path / "events.sqlite3"
    db = TenderDatabase(db_path)
    tender = _tender()
    db.save_tender(tender)
    tender_id = db.get_tender_id(tender.unique_key)
    assert tender_id is not None

    with db._connect() as conn:
        conn.execute("DROP TABLE notification_events")
        conn.execute(
            """
            CREATE TABLE notification_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tender_id INTEGER NOT NULL,
                event_key TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'telegram',
                recipient_key TEXT NOT NULL DEFAULT '__legacy__',
                sent_at TEXT NOT NULL,
                payload TEXT DEFAULT '{}',
                UNIQUE(tender_id, event_key, channel),
                FOREIGN KEY (tender_id) REFERENCES tenders(id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO notification_events
                (tender_id, event_key, channel, recipient_key, sent_at, payload)
            VALUES (?, 'legacy-event', 'telegram', '__legacy__', '2030-01-01T00:00:00+00:00', '{}')
            """,
            (tender_id,),
        )

    reopened = TenderDatabase(db_path)
    state = NotificationDeliveryState(reopened)
    assert state.was_notified(tender) is True

    with reopened._connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(notification_events)")}
        recipients = [row["recipient_key"] for row in conn.execute("SELECT recipient_key FROM notification_events")]
    assert "recipient_key" in columns
    assert recipients == ["__default__"]
