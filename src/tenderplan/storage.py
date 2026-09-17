"""SQLite persistence adapter for TenderPlan tasks."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .tasks import TaskPriority, TaskStatus, TenderTask


class TenderTaskStore:
    """Persist TenderTask objects in the application's SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tender_tasks (
                    task_id TEXT PRIMARY KEY,
                    tender_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    due_at TEXT,
                    responsible TEXT NOT NULL DEFAULT '',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    status TEXT NOT NULL DEFAULT 'todo',
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    notes TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tender_tasks_tender ON tender_tasks(tender_key)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tender_tasks_due_status ON tender_tasks(due_at, status)"
            )
            conn.commit()

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.astimezone(timezone.utc).isoformat() if value else None

    @staticmethod
    def _parse(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value).astimezone(timezone.utc)

    def save(self, task: TenderTask) -> TenderTask:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tender_tasks
                    (task_id, tender_key, title, due_at, responsible, priority, status,
                     created_at, completed_at, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    tender_key=excluded.tender_key,
                    title=excluded.title,
                    due_at=excluded.due_at,
                    responsible=excluded.responsible,
                    priority=excluded.priority,
                    status=excluded.status,
                    created_at=excluded.created_at,
                    completed_at=excluded.completed_at,
                    notes=excluded.notes
                """,
                (
                    task.task_id,
                    task.tender_key,
                    task.title,
                    self._iso(task.due_at),
                    task.responsible,
                    task.priority.value,
                    task.status.value,
                    self._iso(task.created_at),
                    self._iso(task.completed_at),
                    task.notes,
                ),
            )
            conn.commit()
        return task

    def get(self, task_id: str) -> TenderTask | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tender_tasks WHERE task_id = ?", (str(task_id),)
            ).fetchone()
        if row is None:
            return None
        return TenderTask(
            task_id=row["task_id"],
            tender_key=row["tender_key"],
            title=row["title"],
            due_at=self._parse(row["due_at"]),
            responsible=row["responsible"],
            priority=TaskPriority(row["priority"]),
            status=TaskStatus(row["status"]),
            created_at=self._parse(row["created_at"]),
            completed_at=self._parse(row["completed_at"]),
            notes=row["notes"],
        )

    def list_for_tender(self, tender_key: str) -> list[TenderTask]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tender_tasks WHERE tender_key = ? ORDER BY due_at, created_at, task_id",
                (str(tender_key),),
            ).fetchall()
        return [
            TenderTask(
                task_id=row["task_id"],
                tender_key=row["tender_key"],
                title=row["title"],
                due_at=self._parse(row["due_at"]),
                responsible=row["responsible"],
                priority=TaskPriority(row["priority"]),
                status=TaskStatus(row["status"]),
                created_at=self._parse(row["created_at"]),
                completed_at=self._parse(row["completed_at"]),
                notes=row["notes"],
            )
            for row in rows
        ]

    def list_open(self, *, due_before: datetime | None = None) -> list[TenderTask]:
        sql = "SELECT * FROM tender_tasks WHERE status IN ('todo', 'in_progress')"
        params: list[str] = []
        if due_before is not None:
            sql += " AND due_at IS NOT NULL AND due_at <= ?"
            params.append(self._iso(due_before) or "")
        sql += " ORDER BY due_at, created_at, task_id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            TenderTask(
                task_id=row["task_id"],
                tender_key=row["tender_key"],
                title=row["title"],
                due_at=self._parse(row["due_at"]),
                responsible=row["responsible"],
                priority=TaskPriority(row["priority"]),
                status=TaskStatus(row["status"]),
                created_at=self._parse(row["created_at"]),
                completed_at=self._parse(row["completed_at"]),
                notes=row["notes"],
            )
            for row in rows
        ]

    def delete(self, task_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tender_tasks WHERE task_id = ?", (str(task_id),))
            conn.commit()
