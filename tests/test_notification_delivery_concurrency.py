from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from src.models.tender import Tender
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState


def _tender() -> Tender:
    return Tender(
        platform="test",
        external_id="claim-1",
        title="Конкурентный тендер",
        url="https://example.test/claim-1",
        price=1000.0,
        deadline=datetime.now(timezone.utc) + timedelta(days=10),
    )


def test_only_one_concurrent_delivery_claim_wins(tmp_path):
    db = TenderDatabase(tmp_path / "claims.db")
    tender = _tender()
    db.save_tender(tender)

    states = [NotificationDeliveryState(db) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda state: state.was_notified(tender), states))

    assert results.count(False) == 1
    assert results.count(True) == 7


def test_successful_delivery_releases_claim_and_records_event(tmp_path):
    db = TenderDatabase(tmp_path / "release.db")
    state = NotificationDeliveryState(db)
    tender = _tender()
    db.save_tender(tender)

    assert state.was_notified(tender) is False
    state.mark_notified(tender)
    assert state.was_notified(tender) is True

    with db._connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM notification_delivery_claims").fetchone()
    assert row["c"] == 0
    assert db.count_notifications() == 1


def test_stale_claim_is_reclaimed(tmp_path):
    db = TenderDatabase(tmp_path / "stale.db")
    state = NotificationDeliveryState(db)
    tender = _tender()
    tender_id = db.save_tender(tender)
    event_key = state.event_key(tender)
    stale = (datetime.now(timezone.utc) - state.CLAIM_TTL - timedelta(seconds=1)).isoformat()

    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO notification_delivery_claims
                (tender_id, event_key, channel, recipient_key, claimed_at)
            VALUES (?, ?, 'telegram', '__default__', ?)
            """,
            (tender_id, event_key, stale),
        )

    assert state.was_notified(tender) is False
