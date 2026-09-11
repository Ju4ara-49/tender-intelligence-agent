"""Stateful notification deduplication for tender changes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from src.models.tender import Tender
from src.storage.database import TenderDatabase


class NotificationDeliveryState:
    """Tracks notification delivery by a meaningful Tender state fingerprint.

    The legacy database keeps a one-row-per-tender compatibility table. This
    service adds a richer event fingerprint without requiring a destructive
    migration of the existing SQLite schema.
    """

    CHANNEL = "telegram"

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db

    @staticmethod
    def event_key(tender: Tender) -> str:
        state = {
            "title": tender.title,
            "url": tender.url,
            "price": tender.price,
            "currency": tender.currency,
            "start_date": tender.start_date.isoformat() if tender.start_date else None,
            "end_date": tender.end_date.isoformat() if tender.end_date else None,
            "deadline": tender.deadline.isoformat() if tender.deadline else None,
            "published_at": tender.published_at.isoformat() if tender.published_at else None,
            "region": tender.region,
            "customer": tender.customer,
            "law_type": tender.law_type,
            "advance_required": tender.advance_required,
            "advance_percent": tender.advance_percent,
            "postpayment_days": tender.postpayment_days,
            "application_security_percent": tender.application_security_percent,
            "contract_security_percent": tender.contract_security_percent,
        }
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def was_notified(self, tender: Tender) -> bool:
        tender_id = self.db.get_tender_id(tender.unique_key)
        if tender_id is None:
            return False
        key = self.event_key(tender)
        with self.db._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM notification_events WHERE tender_id = ? AND event_key = ? AND channel = ?",
                (tender_id, key, self.CHANNEL),
            ).fetchone()
            if row is not None:
                return True

            # Upgrade bridge: old installations may have only the legacy row.
            # Treat the current state as the already-delivered baseline once,
            # then future changes will be detected by the richer fingerprint.
            legacy = conn.execute(
                "SELECT sent_at, payload, channel FROM notifications WHERE tender_id = ? ORDER BY id DESC LIMIT 1",
                (tender_id,),
            ).fetchone()
            if legacy is None:
                return False
            conn.execute(
                """
                INSERT OR IGNORE INTO notification_events
                    (tender_id, event_key, channel, sent_at, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tender_id, key, legacy["channel"] or self.CHANNEL, legacy["sent_at"], legacy["payload"] or "{}"),
            )
            return True

    def mark_notified(self, tender: Tender, payload: dict | None = None) -> None:
        tender_id = self.db.get_tender_id(tender.unique_key)
        if tender_id is None:
            raise ValueError(f"Tender not found: {tender.unique_key}")
        self.db.mark_notified(tender_id, channel=self.CHANNEL, payload=payload)
        key = self.event_key(tender)
        now = datetime.now(timezone.utc).isoformat()
        with self.db._connect() as conn:
            conn.execute(
                """
                INSERT INTO notification_events
                    (tender_id, event_key, channel, sent_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tender_id, event_key, channel) DO UPDATE SET
                    sent_at = excluded.sent_at,
                    payload = excluded.payload
                """,
                (tender_id, key, self.CHANNEL, now, json.dumps(payload or {}, ensure_ascii=False)),
            )
