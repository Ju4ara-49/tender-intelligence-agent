"""SQLite persistence for deterministic tender risk assessments."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.risk.engine import RiskAssessment, RiskFactor


class RiskAssessmentStore:
    """Persist risk assessments without coupling the risk engine to the DB layer."""

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
                CREATE TABLE IF NOT EXISTS risk_assessments (
                    tender_id INTEGER PRIMARY KEY,
                    level TEXT NOT NULL,
                    factors TEXT NOT NULL DEFAULT '[]',
                    assessed_at TEXT NOT NULL,
                    FOREIGN KEY (tender_id) REFERENCES tenders(id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()

    def save(self, tender_id: int, assessment: RiskAssessment, *, assessed_at: datetime | None = None) -> None:
        moment = assessed_at or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        payload = json.dumps(assessment.to_dict()["factors"], ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO risk_assessments (tender_id, level, factors, assessed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tender_id) DO UPDATE SET
                    level = excluded.level,
                    factors = excluded.factors,
                    assessed_at = excluded.assessed_at
                """,
                (tender_id, assessment.level, payload, moment.astimezone(timezone.utc).isoformat()),
            )
            conn.commit()

    def get(self, tender_id: int) -> RiskAssessment | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT level, factors FROM risk_assessments WHERE tender_id = ?",
                (tender_id,),
            ).fetchone()
        if row is None:
            return None
        raw_factors = json.loads(row["factors"] or "[]")
        factors = [RiskFactor(**item) for item in raw_factors if isinstance(item, dict)]
        return RiskAssessment(level=row["level"], factors=factors)

    def delete(self, tender_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM risk_assessments WHERE tender_id = ?", (tender_id,))
            conn.commit()
