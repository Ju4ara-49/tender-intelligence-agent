"""Хранение данных в SQLite."""

from __future__ import annotations

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
    """SQLite-хранилище тендеров с защитой от дублей и истории изменений."""

    SQLITE_TIMEOUT_SECONDS = 15.0
    BUSY_TIMEOUT_MS = 15000

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
                    deadline TEXT,
                    published_at TEXT,
                    region TEXT DEFAULT '',
                    customer TEXT DEFAULT '',
                    law_type TEXT DEFAULT '',
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
                """
            )

    def next_search_number(self) -> int:
        """Атомарно получить следующий номер поиска в SQLite."""
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

    def was_notified(self, unique_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM notifications n JOIN tenders t ON t.id = n.tender_id WHERE t.unique_key = ?",
                (unique_key,),
            ).fetchone()
        return row is not None

    @staticmethod
    def _tender_snapshot(tender: Tender) -> dict:
        return {
            "platform": tender.platform, "external_id": tender.external_id, "unique_key": tender.unique_key,
            "title": tender.title, "url": tender.url, "description": tender.description, "price": tender.price,
            "currency": tender.currency, "deadline": tender.deadline.isoformat() if tender.deadline else None,
            "published_at": tender.published_at.isoformat() if tender.published_at else None,
            "region": tender.region, "customer": tender.customer, "law_type": tender.law_type, "raw_data": tender.raw_data,
        }

    def save_tender(self, tender: Tender) -> int:
        now = datetime.now(timezone.utc).isoformat()
        snapshot = self._tender_snapshot(tender)
        tracked_fields = ("title", "url", "description", "price", "currency", "deadline", "published_at", "region", "customer", "law_type", "raw_data")
        with self._connect() as conn:
            previous = conn.execute("SELECT * FROM tenders WHERE unique_key = ?", (tender.unique_key,)).fetchone()
            conn.execute(
                """
                INSERT INTO tenders (platform, external_id, unique_key, title, url, description, price, currency, deadline, published_at, region, customer, law_type, raw_data, first_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(unique_key) DO UPDATE SET
                    platform = excluded.platform, external_id = excluded.external_id, title = excluded.title,
                    url = excluded.url, description = excluded.description, price = excluded.price,
                    currency = excluded.currency, deadline = excluded.deadline, published_at = excluded.published_at,
                    region = excluded.region, customer = excluded.customer, law_type = excluded.law_type,
                    raw_data = excluded.raw_data, updated_at = excluded.updated_at
                """,
                (tender.platform, tender.external_id, tender.unique_key, tender.title, tender.url, tender.description,
                 tender.price, tender.currency, tender.deadline.isoformat() if tender.deadline else None,
                 tender.published_at.isoformat() if tender.published_at else None, tender.region, tender.customer,
                 tender.law_type, json.dumps(tender.raw_data, ensure_ascii=False), now, now),
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
                    "price": previous["price"], "currency": previous["currency"], "deadline": previous["deadline"],
                    "published_at": previous["published_at"], "region": previous["region"], "customer": previous["customer"],
                    "law_type": previous["law_type"], "raw_data": previous["raw_data"],
                }
                current_values = {
                    "title": snapshot["title"], "url": snapshot["url"], "description": snapshot["description"],
                    "price": snapshot["price"], "currency": snapshot["currency"], "deadline": snapshot["deadline"],
                    "published_at": snapshot["published_at"], "region": snapshot["region"], "customer": snapshot["customer"],
                    "law_type": snapshot["law_type"], "raw_data": json.dumps(snapshot["raw_data"], ensure_ascii=False),
                }
                changed_fields = [field for field in tracked_fields if previous_values[field] != current_values[field]]
                event_type = "updated"
            if changed_fields:
                conn.execute(
                    "INSERT INTO tender_history (tender_id, changed_at, event_type, changed_fields, snapshot) VALUES (?, ?, ?, ?, ?)",
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
                INSERT INTO analyses (tender_id, relevance_score, summary, recommendation, risks, budget_note, deadline_note, is_stub, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tender_id) DO UPDATE SET relevance_score = excluded.relevance_score,
                    summary = excluded.summary, recommendation = excluded.recommendation, risks = excluded.risks,
                    budget_note = excluded.budget_note, deadline_note = excluded.deadline_note,
                    is_stub = excluded.is_stub, analyzed_at = excluded.analyzed_at
                """,
                (tender_id, analysis.relevance_score, analysis.summary, analysis.recommendation,
                 json.dumps(analysis.risks, ensure_ascii=False), analysis.budget_note, analysis.deadline_note,
                 1 if analysis.is_stub else 0, now),
            )

    def get_analysis(self, tender_id: int) -> TenderAnalysis | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT relevance_score, summary, recommendation, risks, budget_note, deadline_note, is_stub FROM analyses WHERE tender_id = ?",
                (int(tender_id),),
            ).fetchone()
        if row is None:
            return None
        try:
            risks = json.loads(row["risks"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            risks = []
        return TenderAnalysis(
            relevance_score=int(row["relevance_score"]), summary=row["summary"] or "",
            recommendation=row["recommendation"] or "review", risks=risks,
            budget_note=row["budget_note"] or "", deadline_note=row["deadline_note"] or "",
            is_stub=bool(row["is_stub"]),
        )

    def mark_notified(self, tender_id: int, channel: str = "telegram", payload: dict | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO notifications (tender_id, channel, sent_at, payload) VALUES (?, ?, ?, ?) ON CONFLICT(tender_id) DO NOTHING",
                (tender_id, channel, now, json.dumps(payload or {}, ensure_ascii=False)),
            )

    def count_tenders(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM tenders").fetchone()
        return int(row["c"])

    def count_notifications(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM notifications").fetchone()
        return int(row["c"])
