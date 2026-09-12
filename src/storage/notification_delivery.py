"""Stateful notification deduplication for tender changes."""

from __future__ import annotations

import hashlib
import json

from src.models.tender import Tender
from src.storage.database import TenderDatabase


class NotificationDeliveryState:
    """Tracks notification delivery by a meaningful Tender state fingerprint."""

    CHANNEL = "telegram"
    DEFAULT_RECIPIENT_KEY = TenderDatabase.DEFAULT_RECIPIENT_KEY

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db
        self._repair_legacy_default_events()

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
            "customer_inn": tender.customer_inn,
            "law_type": tender.law_type,
            "advance_required": tender.advance_required,
            "advance_percent": tender.advance_percent,
            "postpayment_days": tender.postpayment_days,
            "application_security_percent": tender.application_security_percent,
            "contract_security_percent": tender.contract_security_percent,
        }
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def _event_key_from_row(cls, row) -> str:
        raw = {}
        try:
            raw = json.loads(row["raw_data"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = {}
        normalized = raw.get("_normalized") if isinstance(raw, dict) else {}
        normalized = normalized if isinstance(normalized, dict) else {}
        state = {
            "title": row["title"],
            "url": row["url"],
            "price": row["price"],
            "currency": row["currency"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "deadline": row["deadline"],
            "published_at": row["published_at"],
            "region": row["region"],
            "customer": row["customer"],
            "customer_inn": row["customer_inn"] or normalized.get("customer_inn", ""),
            "law_type": row["law_type"],
            "advance_required": normalized.get("advance_required", False),
            "advance_percent": normalized.get("advance_percent"),
            "postpayment_days": normalized.get("postpayment_days"),
            "application_security_percent": normalized.get("application_security_percent"),
            "contract_security_percent": normalized.get("contract_security_percent"),
        }
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _repair_legacy_default_events(self) -> None:
        """Bring pre-STEP-25 default-recipient events to the canonical fingerprint."""
        with self.db._connect() as conn:
            rows = conn.execute(
                """
                SELECT n.tender_id, t.title, t.url, t.price, t.currency,
                       t.start_date, t.end_date, t.deadline, t.published_at,
                       t.region, t.customer, t.customer_inn, t.law_type, t.raw_data,
                       n.channel, n.sent_at, n.payload
                FROM notifications n
                JOIN tenders t ON t.id = n.tender_id
                """
            ).fetchall()
            for row in rows:
                key = self._event_key_from_row(row)
                existing = conn.execute(
                    """
                    SELECT id, event_key FROM notification_events
                    WHERE tender_id = ? AND channel = ? AND recipient_key = ?
                    """,
                    (row["tender_id"], row["channel"], self.DEFAULT_RECIPIENT_KEY),
                ).fetchall()
                if len(existing) == 1 and existing[0]["event_key"] == key:
                    continue
                conn.execute(
                    """
                    DELETE FROM notification_events
                    WHERE tender_id = ? AND channel = ? AND recipient_key = ?
                    """,
                    (row["tender_id"], row["channel"], self.DEFAULT_RECIPIENT_KEY),
                )
                conn.execute(
                    """
                    INSERT INTO notification_events
                        (tender_id, event_key, channel, recipient_key, sent_at, payload)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tender_id, event_key, channel, recipient_key) DO UPDATE SET
                        sent_at = excluded.sent_at,
                        payload = excluded.payload
                    """,
                    (
                        row["tender_id"], key, row["channel"], self.DEFAULT_RECIPIENT_KEY,
                        row["sent_at"], row["payload"],
                    ),
                )

    def was_notified(self, tender: Tender, recipient_key: str = DEFAULT_RECIPIENT_KEY) -> bool:
        """Return True only when this exact state was delivered to this recipient."""
        tender_id = self.db.get_tender_id(tender.unique_key)
        if tender_id is None:
            return False
        key = self.event_key(tender)
        with self.db._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM notification_events
                WHERE tender_id = ? AND event_key = ? AND channel = ? AND recipient_key = ?
                """,
                (tender_id, key, self.CHANNEL, recipient_key),
            ).fetchone()
        return row is not None

    def mark_notified(
        self,
        tender: Tender,
        payload: dict | None = None,
        recipient_key: str = DEFAULT_RECIPIENT_KEY,
    ) -> None:
        """Record the rich tender fingerprint as the delivered notification event."""
        tender_id = self.db.get_tender_id(tender.unique_key)
        if tender_id is None:
            raise ValueError(f"Tender not found: {tender.unique_key}")
        self.db.mark_notified(
            tender_id,
            channel=self.CHANNEL,
            payload=payload,
            event_key=self.event_key(tender),
            recipient_key=recipient_key,
        )
