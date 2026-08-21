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
    """SQLite-хранилище тендеров с защитой от дублей."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
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

                CREATE INDEX IF NOT EXISTS idx_tenders_platform
                    ON tenders(platform);
                CREATE INDEX IF NOT EXISTS idx_tenders_first_seen
                    ON tenders(first_seen_at);
                """
            )

    def exists(self, unique_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM tenders WHERE unique_key = ?",
                (unique_key,),
            ).fetchone()
        return row is not None

    def was_notified(self, unique_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM notifications n
                JOIN tenders t ON t.id = n.tender_id
                WHERE t.unique_key = ?
                """,
                (unique_key,),
            ).fetchone()
        return row is not None

    def save_tender(self, tender: Tender) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tenders (
                    platform, external_id, unique_key, title, url, description,
                    price, currency, deadline, published_at, region, customer,
                    law_type, raw_data, first_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(unique_key) DO UPDATE SET
                    title = excluded.title,
                    url = excluded.url,
                    description = excluded.description,
                    price = excluded.price,
                    deadline = excluded.deadline,
                    updated_at = excluded.updated_at
                """,
                (
                    tender.platform,
                    tender.external_id,
                    tender.unique_key,
                    tender.title,
                    tender.url,
                    tender.description,
                    tender.price,
                    tender.currency,
                    tender.deadline.isoformat() if tender.deadline else None,
                    tender.published_at.isoformat() if tender.published_at else None,
                    tender.region,
                    tender.customer,
                    tender.law_type,
                    json.dumps(tender.raw_data, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM tenders WHERE unique_key = ?",
                (tender.unique_key,),
            ).fetchone()
        return int(row["id"])

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
                    analyzed_at = excluded.analyzed_at
                """,
                (
                    tender_id,
                    analysis.relevance_score,
                    analysis.summary,
                    analysis.recommendation,
                    json.dumps(analysis.risks, ensure_ascii=False),
                    analysis.budget_note,
                    analysis.deadline_note,
                    1 if analysis.is_stub else 0,
                    now,
                ),
            )

    def mark_notified(self, tender_id: int, channel: str = "telegram", payload: dict | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notifications (tender_id, channel, sent_at, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tender_id) DO NOTHING
                """,
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
