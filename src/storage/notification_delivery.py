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
    LEGACY_RECIPIENT_KEY = "__legacy__"

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db
        self._repaired_event_keys: dict[int, str] = {}
        self._repair_legacy_default_events()

    @staticmethod
    def _normalized_fields(tender: Tender) -> dict:
        raw = tender.raw_data if isinstance(tender.raw_data, dict) else {}
        normalized = raw.get("_normalized") if isinstance(raw, dict) else {}
        return normalized if isinstance(normalized, dict) else {}

    @classmethod
    def event_key(cls, tender: Tender) -> str:
        normalized = cls._normalized_fields(tender)
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
            "customer_inn": tender.customer_inn or normalized.get("customer_inn", ""),
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
        """Migrate only legacy-recipient events without deleting canonical history."""
        with self.db._connect() as conn:
            rows = conn.execute(
                """
                SELECT n.id AS notification_id, n.tender_id, n.event_key,
                       n.channel, n.sent_at, n.payload,
                       t.title, t.url, t.price, t.currency,
                       t.start_date, t.end_date, t.deadline, t.published_at,
                       t.region, t.customer, t.customer_inn, t.law_type, t.raw_data
                FROM notification_events n
                JOIN tenders t ON t.id = n.tender_id
                WHERE n.recipient_key = ?
                ORDER BY n.id ASC
                """,
                (self.LEGACY_RECIPIENT_KEY,),
            ).fetchall()

            for row in rows:
                key = self._event_key_from_row(row)
                tender_id = int(row["tender_id"])
                self._repaired_event_keys[tender_id] = key

                existing = conn.execute(
                    """
                    SELECT 1 FROM notification_events
                    WHERE tender_id = ? AND event_key = ? AND channel = ? AND recipient_key = ?
                    """,
                    (tender_id, key, row["channel"], self.DEFAULT_RECIPIENT_KEY),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO notification_events
                            (tender_id, event_key, channel, recipient_key, sent_at, payload)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(tender_id, event_key, channel, recipient_key) DO NOTHING
                        """,
                        (
                            tender_id,
                            key,
                            row["channel"],
                            self.DEFAULT_RECIPIENT_KEY,
                            row["sent_at"],
                            row["payload"],
                        ),
                    )

            conn.execute(
                "DELETE FROM notification_events WHERE recipient_key = ?",
                (self.LEGACY_RECIPIENT_KEY,),
            )

    def was_notified(self, tender: Tender, recipient_key: str = DEFAULT_RECIPIENT_KEY) -> bool:
        """Return True only when the exact current Tender state was delivered."""
        event_key = self.event_key(tender)
        with self.db._connect() as conn:
            tender_id = self.db.get_tender_id(tender.unique_key)
            if tender_id is None:
                return False
            row = conn.execute(
                """
                SELECT 1 FROM notification_events
                WHERE tender_id = ? AND event_key = ? AND channel = ? AND recipient_key = ?
                """,
                (tender_id, event_key, self.CHANNEL, recipient_key),
            ).fetchone()
            if row is not None:
                return True

            repaired_key = self._repaired_event_keys.get(tender_id)
            if repaired_key is None or recipient_key != self.DEFAULT_RECIPIENT_KEY:
                return False
            repaired = conn.execute(
                """
                SELECT 1 FROM notification_events
                WHERE tender_id = ? AND event_key = ? AND channel = ? AND recipient_key = ?
                """,
                (tender_id, repaired_key, self.CHANNEL, self.DEFAULT_RECIPIENT_KEY),
            ).fetchone()
        return repaired is not None

    def mark_notified(
        self,
        tender: Tender,
        payload: dict | None = None,
        recipient_key: str = DEFAULT_RECIPIENT_KEY,
    ) -> None:
        """Record the exact current Tender fingerprint."""
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
