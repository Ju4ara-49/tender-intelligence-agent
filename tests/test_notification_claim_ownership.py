from datetime import datetime, timedelta, timezone

from src.models.tender import Tender
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState


def _tender() -> Tender:
    return Tender(
        platform="test",
        external_id="claim-owner-1",
        title="Тестовый тендер",
        url="https://example.test/claim-owner-1",
        price=1000.0,
        deadline=datetime.now(timezone.utc) + timedelta(days=10),
    )


def test_expired_worker_cannot_release_a_claim_renewed_by_another_worker(tmp_path):
    db = TenderDatabase(tmp_path / "claim-owner.db")
    tender = _tender()
    db.save_tender(tender)

    first = NotificationDeliveryState(db)
    second = NotificationDeliveryState(db)
    third = NotificationDeliveryState(db)

    assert first.was_notified(tender) is False

    event_key = first.event_key(tender)
    tender_id = db.get_tender_id(tender.unique_key)
    assert tender_id is not None

    stale_at = (datetime.now(timezone.utc) - first.CLAIM_TTL - timedelta(seconds=1)).isoformat()
    with db._connect() as conn:
        conn.execute(
            """
            UPDATE notification_delivery_claims
            SET claimed_at = ?
            WHERE tender_id = ? AND event_key = ? AND channel = ? AND recipient_key = ?
            """,
            (stale_at, tender_id, event_key, first.CHANNEL, first.DEFAULT_RECIPIENT_KEY),
        )

    # The second worker legitimately takes over after the old lease expires.
    assert second.was_notified(tender) is False

    # The old worker must not delete the second worker's new lease.
    first.release_claim(tender)

    assert third.was_notified(tender) is True
