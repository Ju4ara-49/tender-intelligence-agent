"""SQLite persistence for tender lifecycle state and transition history."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .lifecycle import TenderLifecycleStatus, transition


class TenderLifecycleStore:
    """Persist one lifecycle state per canonical tender identity."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tender_lifecycle (
                    tender_key TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tender_lifecycle_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tender_key TEXT NOT NULL,
                    old_status TEXT,
                    new_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tender_lifecycle_events_key "
                "ON tender_lifecycle_events(tender_key, event_id)"
            )
            conn.commit()

    def get(self, tender_key: str) -> TenderLifecycleStatus | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM tender_lifecycle WHERE tender_key = ?",
                (str(tender_key),),
            ).fetchone()
        return TenderLifecycleStatus(row["status"]) if row else None

    def ensure(
        self,
        tender_key: str,
        status: TenderLifecycleStatus = TenderLifecycleStatus.DISCOVERED,
    ) -> TenderLifecycleStatus:
        now = datetime.now(timezone.utc).isoformat()
        key = str(tender_key)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT OR IGNORE INTO tender_lifecycle (tender_key, status, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, status.value, now),
            )
            row = conn.execute(
                "SELECT status FROM tender_lifecycle WHERE tender_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"lifecycle row was not persisted: {key}")
            actual = TenderLifecycleStatus(row["status"])
            if actual is status:
                event_exists = conn.execute(
                    """
                    SELECT 1 FROM tender_lifecycle_events
                    WHERE tender_key = ? AND old_status IS NULL AND new_status = ?
                    LIMIT 1
                    """,
                    (key, status.value),
                ).fetchone()
                if event_exists is None:
                    conn.execute(
                        """
                        INSERT INTO tender_lifecycle_events
                            (tender_key, old_status, new_status, created_at)
                        VALUES (?, NULL, ?, ?)
                        """,
                        (key, status.value, now),
                    )
            conn.commit()
        return actual

    def set(self, tender_key: str, target: TenderLifecycleStatus) -> TenderLifecycleStatus:
        key = str(tender_key)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            inserted = conn.execute(
                """
                INSERT OR IGNORE INTO tender_lifecycle (tender_key, status, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, TenderLifecycleStatus.DISCOVERED.value, now),
            ).rowcount
            if inserted:
                conn.execute(
                    """
                    INSERT INTO tender_lifecycle_events
                        (tender_key, old_status, new_status, created_at)
                    VALUES (?, NULL, ?, ?)
                    """,
                    (key, TenderLifecycleStatus.DISCOVERED.value, now),
                )
            row = conn.execute(
                "SELECT status FROM tender_lifecycle WHERE tender_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"lifecycle row was not persisted: {key}")
            current = TenderLifecycleStatus(row["status"])
            if current is target:
                conn.commit()
                return current
            next_status = transition(current, target)
            conn.execute(
                "UPDATE tender_lifecycle SET status = ?, updated_at = ? WHERE tender_key = ?",
                (next_status.value, now, key),
            )
            conn.execute(
                """
                INSERT INTO tender_lifecycle_events
                    (tender_key, old_status, new_status, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, current.value, next_status.value, now),
            )
            conn.commit()
        return next_status

    def history(self, tender_key: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, tender_key, old_status, new_status, created_at
                FROM tender_lifecycle_events
                WHERE tender_key = ?
                ORDER BY event_id
                """,
                (str(tender_key),),
            ).fetchall()
        return [dict(row) for row in rows]
