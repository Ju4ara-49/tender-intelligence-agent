"""Stateful notification deduplication for tender changes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from src.models.tender import Tender
from src.storage.database import TenderDatabase


class NotificationDeliveryState:
    """Track delivered notification events and atomically reserve sends."""

    CHANNEL = "telegram"
    DEFAULT_RECIPIENT_KEY = TenderDatabase.DEFAULT_RECIPIENT_KEY
    LEGACY_RECIPIENT_KEY = "__legacy__"
    CLAIM_TTL = timedelta(minutes=10)

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db
        self._repaired_event_keys: dict[int, str] = {}
        self._ensure_claim_schema()
        self._repair_legacy_default_events()

    def _ensure_claim_schema(self) -> None:
        """Create the atomic in-flight delivery reservation table."""
        with self.db._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_delivery_claims (
                    tender_id INTEGER NOT NULL,
                    event_key TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT 'telegram',
                    recipient_key TEXT NOT NULL DEFAULT '__default__',
                    claimed_at TEXT NOT NULL,
                    PRIMARY KEY (tender_id, event_key, channel, recipient_key),
                    FOREIGN KEY (tender_id) REFERENCES tenders(id)
                )
                """
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

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
            "description": tender.description,
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
            "description": row["description"],
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
        """Migrate legacy-recipient events while preserving their event keys."""
        with self.db._connect() as conn:
            rows = conn.execute(
                """
                SELECT n.id AS notification_id, n.tender_id, n.event_key,
                       n.channel, n.sent_at, n.payload
                FROM notification_events n
                WHERE n.recipient_key = ?
                ORDER BY n.id ASC
                """,
                (self.LEGACY_RECIPIENT_KEY,),
            ).fetchall()
            for row in rows:
                key = str(row["event_key"])
                tender_id = int(row["tender_id"])
                self._repaired_event_keys[tender_id] = key
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
        """Return whether this exact event was already recorded as delivered.

        This method is intentionally side-effect free. Delivery reservation is
        a separate operation because callers may need to inspect the state more
        than once before sending.
        """
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
            if repaired_key is not None and recipient_key == self.DEFAULT_RECIPIENT_KEY:
                repaired = conn.execute(
                    """
                    SELECT 1 FROM notification_events
                    WHERE tender_id = ? AND event_key = ? AND channel = ? AND recipient_key = ?
                    """,
                    (tender_id, repaired_key, self.CHANNEL, self.DEFAULT_RECIPIENT_KEY),
                ).fetchone()
                if repaired is not None:
                    return True
            return False

    def claim_delivery(self, tender: Tender, recipient_key: str = DEFAULT_RECIPIENT_KEY) -> bool:
        """Atomically reserve an unsent event for one recipient.

        Returns True only for the caller that owns the send slot. Existing
        delivered events and active claims both return False. Expired claims
        are reclaimed first, so a crashed process cannot block delivery forever.
        """
        event_key = self.event_key(tender)
        with self.db._connect() as conn:
            tender_id_row = conn.execute(
                "SELECT id FROM tenders WHERE unique_key = ?",
                (tender.unique_key,),
            ).fetchone()
            if tender_id_row is None:
                return False
            tender_id = int(tender_id_row["id"])

            delivered = conn.execute(
                """
                SELECT 1 FROM notification_events
                WHERE tender_id = ? AND event_key = ? AND channel = ? AND recipient_key = ?
                """,
                (tender_id, event_key, self.CHANNEL, recipient_key),
            ).fetchone()
            if delivered is not None:
                return False

            repaired_key = self._repaired_event_keys.get(tender_id)
            if repaired_key is not None and recipient_key == self.DEFAULT_RECIPIENT_KEY:
                repaired = conn.execute(
                    """
                    SELECT 1 FROM notification_events
                    WHERE tender_id = ? AND event_key = ? AND channel = ? AND recipient_key = ?
                    """,
                    (tender_id, repaired_key, self.CHANNEL, self.DEFAULT_RECIPIENT_KEY),
                ).fetchone()
                if repaired is not None:
                    return False

            cutoff = (self._now() - self.CLAIM_TTL).isoformat()
            conn.execute("DELETE FROM notification_delivery_claims WHERE claimed_at < ?", (cutoff,))
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO notification_delivery_claims
                    (tender_id, event_key, channel, recipient_key, claimed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tender_id, event_key, self.CHANNEL, recipient_key, self._now().isoformat()),
            )
            return cursor.rowcount == 1

    def release_claim(self, tender: Tender, recipient_key: str = DEFAULT_RECIPIENT_KEY) -> None:
        """Release an in-flight claim after an external send failure."""
        tender_id = self.db.get_tender_id(tender.unique_key)
        if tender_id is None:
            return
        event_key = self.event_key(tender)
        with self.db._connect() as conn:
            conn.execute(
                """
                DELETE FROM notification_delivery_claims
                WHERE tender_id = ? AND event_key = ? AND channel = ? AND recipient_key = ?
                """,
                (tender_id, event_key, self.CHANNEL, recipient_key),
            )

    def mark_notified(
        self,
        tender: Tender,
        payload: dict | None = None,
        recipient_key: str = DEFAULT_RECIPIENT_KEY,
    ) -> None:
        """Record the exact current Tender fingerprint and release its claim."""
        tender_id = self.db.get_tender_id(tender.unique_key)
        if tender_id is None:
            raise ValueError(f"Tender not found: {tender.unique_key}")
        event_key = self.event_key(tender)
        self.db.mark_notified(
            tender_id,
            channel=self.CHANNEL,
            payload=payload,
            event_key=event_key,
            recipient_key=recipient_key,
        )
        with self.db._connect() as conn:
            conn.execute(
                """
                DELETE FROM notification_delivery_claims
                WHERE tender_id = ? AND event_key = ? AND channel = ? AND recipient_key = ?
                """,
                (tender_id, event_key, self.CHANNEL, recipient_key),
            )
