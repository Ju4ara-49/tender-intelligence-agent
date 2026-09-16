"""Хранение данных в SQLite."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from src.models.tender import Tender, TenderAnalysis

logger = logging.getLogger(__name__)


class TenderDatabase:
    """SQLite-хранилище тендеров с защитой от дублей и историей изменений."""

    SQLITE_TIMEOUT_SECONDS = 15.0
    BUSY_TIMEOUT_MS = 15000
    DEFAULT_RECIPIENT_KEY = "__default__"

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=self.SQLITE_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(f"PRAGMA busy_timeout = {self.BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tenders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    unique_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    price REAL,
                    currency TEXT DEFAULT 'RUB',
                    start_date TEXT,
                    end_date TEXT,
                    deadline TEXT,
                    published_at TEXT,
                    region TEXT DEFAULT '',
                    customer TEXT DEFAULT '',
                    customer_inn TEXT DEFAULT '',
                    law_type TEXT DEFAULT '',
                    detail_status TEXT NOT NULL DEFAULT 'partial',
                    detail_diagnostics TEXT DEFAULT '',
                    raw_data TEXT DEFAULT '{}',
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tender_id INTEGER NOT NULL UNIQUE,
                    relevance_score INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    risks TEXT DEFAULT '[]',
                    budget_note TEXT DEFAULT '',
                    deadline_note TEXT DEFAULT '',
                    is_stub INTEGER DEFAULT 0,
                    analyzed_at TEXT NOT NULL,
                    FOREIGN KEY (tender_id) REFERENCES tenders(id)
                );

                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tender_id INTEGER NOT NULL UNIQUE,
                    channel TEXT NOT NULL DEFAULT 'telegram',
                    sent_at TEXT NOT NULL,
                    payload TEXT DEFAULT '{}',
                    FOREIGN KEY (tender_id) REFERENCES tenders(id)
                );

                CREATE TABLE IF NOT EXISTS notification_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tender_id INTEGER NOT NULL,
                    event_key TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT 'telegram',
                    recipient_key TEXT NOT NULL DEFAULT '__default__',
                    sent_at TEXT NOT NULL,
                    payload TEXT DEFAULT '{}',
                    UNIQUE(tender_id, event_key, channel, recipient_key),
                    FOREIGN KEY (tender_id) REFERENCES tenders(id)
                );

                CREATE TABLE IF NOT EXISTS tender_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tender_id INTEGER NOT NULL,
                    changed_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    changed_fields TEXT NOT NULL DEFAULT '[]',
                    snapshot TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (tender_id) REFERENCES tenders(id)
                );

                CREATE TABLE IF NOT EXISTS search_counter (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    value INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_tenders_platform ON tenders(platform);
                CREATE INDEX IF NOT EXISTS idx_tenders_first_seen ON tenders(first_seen_at);
                CREATE INDEX IF NOT EXISTS idx_tender_history_tender_changed ON tender_history(tender_id, changed_at);
                CREATE INDEX IF NOT EXISTS idx_notification_events_tender ON notification_events(tender_id, sent_at);
                """
            )
            self._migrate_tender_schema(conn)
            self._migrate_notification_events(conn)
            self._migrate_legacy_notifications(conn)

    @staticmethod
    def _migrate_tender_schema(conn: sqlite3.Connection) -> None:
        """Add new normalized tender fields to existing databases."""
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tenders)").fetchall()}
        migrations = {
            "start_date": "TEXT",
            "end_date": "TEXT",
            "customer_inn": "TEXT NOT NULL DEFAULT ''",
            "detail_status": "TEXT NOT NULL DEFAULT 'partial'",
            "detail_diagnostics": "TEXT DEFAULT ''",
        }
        for column, definition in migrations.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE tenders ADD COLUMN {column} {definition}")
                logger.info("SQLite migration: added tenders.%s", column)

    @classmethod
    def _migrate_notification_events(cls, conn: sqlite3.Connection) -> None:
        """Rebuild notification_events when recipient-aware uniqueness is absent."""
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(notification_events)").fetchall()}
        indexes = conn.execute("PRAGMA index_list(notification_events)").fetchall()
        has_recipient = "recipient_key" in columns
        has_recipient_unique = False
        if has_recipient:
            required = {"tender_id", "event_key", "channel", "recipient_key"}
            for index in indexes:
                if not index["unique"]:
                    continue
                index_columns = {
                    str(index_row["name"])
                    for index_row in conn.execute(f"PRAGMA index_info({index['name']})").fetchall()
                }
                if index_columns == required:
                    has_recipient_unique = True
                    break
        if has_recipient and has_recipient_unique:
            return

        conn.execute("DROP TABLE IF EXISTS notification_events_new")
        conn.execute(
            """
            CREATE TABLE notification_events_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tender_id INTEGER NOT NULL,
                event_key TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'telegram',
                recipient_key TEXT NOT NULL DEFAULT '__default__',
                sent_at TEXT NOT NULL,
                payload TEXT DEFAULT '{}',
                UNIQUE(tender_id, event_key, channel, recipient_key),
                FOREIGN KEY (tender_id) REFERENCES tenders(id)
            )
            """
        )
        source_columns = {row["name"] for row in conn.execute("PRAGMA table_info(notification_events)").fetchall()}
        recipient_expression = "recipient_key" if "recipient_key" in source_columns else "'__legacy__'"
        conn.execute(
            f"""
            INSERT INTO notification_events_new
                (id, tender_id, event_key, channel, recipient_key, sent_at, payload)
            SELECT id, tender_id, event_key, channel, {recipient_expression}, sent_at, payload
            FROM notification_events
            """
        )
        conn.execute("DROP TABLE notification_events")
        conn.execute("ALTER TABLE notification_events_new RENAME TO notification_events")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notification_events_tender ON notification_events(tender_id, sent_at)")
        conn.execute("PRAGMA foreign_key_check")

    @staticmethod
    def _notification_event_key_from_row(row: sqlite3.Row) -> str:
        """Stable fingerprint of notification-significant business fields."""
        def value(name: str):
            try:
                return row[name]
            except (IndexError, KeyError):
                return None

        raw_data = {}
        raw_value = value("raw_data")
        if raw_value:
            try:
                parsed = json.loads(raw_value)
                if isinstance(parsed, dict):
                    raw_data = parsed
            except (TypeError, ValueError, json.JSONDecodeError):
                raw_data = {}
        normalized = raw_data.get("_normalized") if isinstance(raw_data, dict) else {}
        if not isinstance(normalized, dict):
            normalized = {}

        state = {
            "title": value("title"),
            "description": value("description"),
            "url": value("url"),
            "price": value("price"),
            "currency": value("currency"),
            "start_date": value("start_date"),
            "end_date": value("end_date"),
            "deadline": value("deadline"),
            "published_at": value("published_at"),
            "region": value("region"),
            "customer": value("customer"),
            "customer_inn": value("customer_inn") or normalized.get("customer_inn", ""),
            "law_type": value("law_type"),
            "advance_required": normalized.get("advance_required", False),
            "advance_percent": normalized.get("advance_percent"),
            "postpayment_days": normalized.get("postpayment_days"),
            "application_security_percent": normalized.get("application_security_percent"),
            "contract_security_percent": normalized.get("contract_security_percent"),
        }
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _migrate_legacy_notifications(self, conn: sqlite3.Connection) -> None:
        """Перенести старые одноразовые уведомления в event-доставку без дублей."""
        rows = conn.execute(
            """
            SELECT n.tender_id, n.channel, n.sent_at, n.payload,
                   t.title, t.description, t.url, t.price, t.currency, t.start_date, t.end_date,
                   t.deadline, t.published_at, t.region, t.customer,
                   t.customer_inn, t.law_type, t.raw_data
            FROM notifications n
            JOIN tenders t ON t.id = n.tender_id
            """
        ).fetchall()
        for row in rows:
            event_key = self._notification_event_key_from_row(row)
            conn.execute(
                """
                INSERT OR IGNORE INTO notification_events
                    (tender_id, event_key, channel, recipient_key, sent_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (row["tender_id"], event_key, row["channel"], self.DEFAULT_RECIPIENT_KEY, row["sent_at"], row["payload"]),
            )

    def next_search_number(self) -> int:
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO search_counter(id, value) VALUES (1, 0)")
            conn.execute("UPDATE search_counter SET value = value + 1 WHERE id = 1")
            row = conn.execute("SELECT value FROM search_counter WHERE id = 1").fetchone()
            if row is None:
                raise RuntimeError("Не удалось получить номер поиска")
            return int(row["value"])

    def exists(self, unique_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM tenders WHERE unique_key = ?", (unique_key,)).fetchone()
        return row is not None

    def get_tender_id(self, unique_key: str) -> int | None:
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM tenders WHERE unique_key = ?", (unique_key,)).fetchone()
        return int(row["id"]) if row is not None else None

    def _current_notification_event_key(self, unique_key: str) -> tuple[int, str] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, description, url, price, currency, start_date, end_date,
                       deadline, published_at, region, customer, customer_inn, law_type,
                       raw_data
                FROM tenders WHERE unique_key = ?
                """,
                (unique_key,),
            ).fetchone()
        if row is None:
            return None
        return int(row["id"]), self._notification_event_key_from_row(row)

    def was_notified(
        self,
        unique_key: str,
        channel: str = "telegram",
        recipient_key: str = DEFAULT_RECIPIENT_KEY,
    ) -> bool:
        current = self._current_notification_event_key(unique_key)
        if current is None:
            return False
        tender_id, event_key = current
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM notification_events
                WHERE tender_id = ? AND event_key = ? AND channel = ? AND recipient_key = ?
                """,
                (tender_id, event_key, channel, recipient_key),
            ).fetchone()
        return row is not None

    @staticmethod
    def _tender_snapshot(tender: Tender) -> dict:
        return {
            "platform": tender.platform,
            "external_id": tender.external_id,
            "unique_key": tender.unique_key,
            "title": tender.title,
            "url": tender.url,
            "description": tender.description,
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
            "detail_status": tender.detail_status,
            "detail_diagnostics": tender.detail_diagnostics,
            "raw_data": tender.raw_data,
        }

    def save_tender(self, tender: Tender) -> int:
        now = datetime.now(timezone.utc).isoformat()
        snapshot = self._tender_snapshot(tender)
        tracked_fields = (
            "title", "url", "description", "price", "currency", "start_date", "end_date",
            "deadline", "published_at", "region", "customer", "customer_inn", "law_type",
            "raw_data",
        )
        with self._connect() as conn:
            previous = conn.execute("SELECT * FROM tenders WHERE unique_key = ?", (tender.unique_key,)).fetchone()
            conn.execute(
                """
                INSERT INTO tenders (
                    platform, external_id, unique_key, title, url, description,
                    price, currency, start_date, end_date, deadline, published_at,
                    region, customer, customer_inn, law_type, detail_status, detail_diagnostics,
                    raw_data, first_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(unique_key) DO UPDATE SET
                    platform = excluded.platform,
                    external_id = excluded.external_id,
                    title = excluded.title,
                    url = excluded.url,
                    description = excluded.description,
                    price = excluded.price,
                    currency = excluded.currency,
                    start_date = excluded.start_date,
                    end_date = excluded.end_date,
                    deadline = excluded.deadline,
                    published_at = excluded.published_at,
                    region = excluded.region,
                    customer = excluded.customer,
                    customer_inn = excluded.customer_inn,
                    law_type = excluded.law_type,
                    detail_status = excluded.detail_status,
                    detail_diagnostics = excluded.detail_diagnostics,
                    raw_data = excluded.raw_data,
                    updated_at = excluded.updated_at
                """,
                (
                    tender.platform, tender.external_id, tender.unique_key, tender.title, tender.url,
                    tender.description, tender.price, tender.currency,
                    tender.start_date.isoformat() if tender.start_date else None,
                    tender.end_date.isoformat() if tender.end_date else None,
                    tender.published_at.isoformat() if tender.published_at else None,
                    tender.region, tender.customer, tender.customer_inn, tender.law_type,
                    tender.detail_status, tender.detail_diagnostics,
                    json.dumps(tender.raw_data, ensure_ascii=False), now, now,
                ),
            )
            row = conn.execute("SELECT * FROM tenders WHERE unique_key = ?", (tender.unique_key,)).fetchone()
            if row is None:
                raise RuntimeError(f"Tender was not saved: {tender.unique_key}")
            tender_id = int(row["id"])

            if previous is None:
                changed_fields = ["created"]
                event_type = "created"
            else:
                previous_values = {
                    "title": previous["title"], "url": previous["url"], "description": previous["description"],
                    "price": previous["price"], "currency": previous["currency"],
                    "start_date": previous["start_date"], "end_date": previous["end_date"],
                    "deadline": previous["deadline"], "published_at": previous["published_at"],
                    "region": previous["region"], "customer": previous["customer"],
                    "customer_inn": previous["customer_inn"], "law_type": previous["law_type"],
                    "raw_data": previous["raw_data"],
                }
                current_values = {
                    "title": snapshot["title"], "url": snapshot["url"], "description": snapshot["description"],
                    "price": snapshot["price"], "currency": snapshot["currency"],
                    "start_date": snapshot["start_date"], "end_date": snapshot["end_date"],
                    "deadline": snapshot["deadline"], "published_at": snapshot["published_at"],
                    "region": snapshot["region"], "customer": snapshot["customer"],
                    "customer_inn": snapshot["customer_inn"], "law_type": snapshot["law_type"],
                    "raw_data": json.dumps(snapshot["raw_data"], ensure_ascii=False),
                }
                changed_fields = [field for field in tracked_fields if previous_values[field] != current_values[field]]
                event_type = "updated"

            if changed_fields:
                conn.execute(
                    """
                    INSERT INTO tender_history (tender_id, changed_at, event_type, changed_fields, snapshot)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (tender_id, now, event_type, json.dumps(changed_fields, ensure_ascii=False), json.dumps(snapshot, ensure_ascii=False)),
                )
        return tender_id

    def get_tender_history(self, tender_id: int) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT id, tender_id, changed_at, event_type, changed_fields, snapshot FROM tender_history WHERE tender_id = ? ORDER BY changed_at ASC, id ASC",
                (tender_id,),
            ).fetchall()

    def save_analysis(self, tender_id: int, analysis: TenderAnalysis) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO analyses (
                    tender_id, relevance_score, summary, recommendation,
                    risks, budget_note, deadline_note, is_stub, analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tender_id) DO UPDATE SET
                    relevance_score = excluded.relevance_score,
                    summary = excluded.summary,
                    recommendation = excluded.recommendation,
                    risks = excluded.risks,
                    budget_note = excluded.budget_note,
                    deadline_note = excluded.deadline_note,
                    is_stub = excluded.is_stub,
                    analyzed_at = excluded.analyzed_at
                """,
                (tender_id, analysis.relevance_score, analysis.summary, analysis.recommendation, json.dumps(analysis.risks, ensure_ascii=False), analysis.budget_note, analysis.deadline_note, 1 if analysis.is_stub else 0, now),
            )

    def mark_notified(
        self,
        tender_id: int,
        channel: str = "telegram",
        payload: dict | None = None,
        event_key: str | None = None,
        recipient_key: str = DEFAULT_RECIPIENT_KEY,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            tender = conn.execute(
                "SELECT id, title, description, url, price, currency, start_date, end_date, deadline, published_at, region, customer, customer_inn, law_type, raw_data FROM tenders WHERE id = ?",
                (tender_id,),
            ).fetchone()
            if tender is None:
                raise ValueError(f"Tender not found: {tender_id}")
            event_key = event_key or self._notification_event_key_from_row(tender)
            conn.execute(
                """
                INSERT INTO notification_events
                    (tender_id, event_key, channel, recipient_key, sent_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tender_id, event_key, channel, recipient_key) DO UPDATE SET
                    sent_at = excluded.sent_at,
                    payload = excluded.payload
                """,
                (tender_id, event_key, channel, recipient_key, now, json.dumps(payload or {}, ensure_ascii=False)),
            )
            conn.execute(
                """
                INSERT INTO notifications (tender_id, channel, sent_at, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tender_id) DO UPDATE SET
                    channel = excluded.channel,
                    sent_at = excluded.sent_at,
                    payload = excluded.payload
                """,
                (tender_id, channel, now, json.dumps(payload or {}, ensure_ascii=False)),
            )

    def count_tenders(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM tenders").fetchone()
        return int(row["c"])

    def count_notifications(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM notification_events").fetchone()
        return int(row["c"])
