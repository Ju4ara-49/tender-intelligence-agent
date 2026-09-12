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
