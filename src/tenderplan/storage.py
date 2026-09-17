"""SQLite persistence adapter for TenderPlan tasks."""

from __future__ import annotations

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tender_task_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    field_name TEXT NOT NULL DEFAULT '',
                    old_value TEXT,
                    new_value TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tender_task_events_task ON tender_task_events(task_id, event_id)"
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

    @staticmethod
    def _task_values(task: TenderTask) -> dict[str, str | None]:
        return {
            "tender_key": task.tender_key,
            "title": task.title,
            "due_at": TenderTaskStore._iso(task.due_at),
            "responsible": task.responsible,
            "priority": task.priority.value,
            "status": task.status.value,
            "created_at": TenderTaskStore._iso(task.created_at),
            "completed_at": TenderTaskStore._iso(task.completed_at),
            "notes": task.notes,
        }

    def _record_event(
        self,
        conn: sqlite3.Connection,
        *,
        task_id: str,
        event_type: str,
        field_name: str = "",
        old_value: str | None = None,
        new_value: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO tender_task_events
                (task_id, event_type, field_name, old_value, new_value, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(task_id),
                str(event_type),
                str(field_name),
                old_value,
                new_value,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def save(self, task: TenderTask) -> TenderTask:
        values = self._task_values(task)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM tender_tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()
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
                    values["tender_key"],
                    values["title"],
                    values["due_at"],
                    values["responsible"],
                    values["priority"],
                    values["status"],
                    values["created_at"],
                    values["completed_at"],
                    values["notes"],
                ),
            )
            if existing is None:
                self._record_event(conn, task_id=task.task_id, event_type="created")
            else:
                for field_name in (
                    "tender_key",
                    "title",
                    "due_at",
                    "responsible",
                    "priority",
                    "status",
                    "completed_at",
                    "notes",
                ):
                    old_value = existing[field_name]
                    new_value = values[field_name]
                    if old_value != new_value:
                        event_type = "status_changed" if field_name == "status" else "field_changed"
                        self._record_event(
                            conn,
                            task_id=task.task_id,
                            event_type=event_type,
                            field_name=field_name,
                            old_value=old_value,
                            new_value=new_value,
                        )
            conn.commit()
        return task

    @staticmethod
    def _from_row(row: sqlite3.Row) -> TenderTask:
        return TenderTask(
            task_id=row["task_id"],
            tender_key=row["tender_key"],
            title=row["title"],
            due_at=TenderTaskStore._parse(row["due_at"]),
            responsible=row["responsible"],
            priority=TaskPriority(row["priority"]),
            status=TaskStatus(row["status"]),
            created_at=TenderTaskStore._parse(row["created_at"]),
            completed_at=TenderTaskStore._parse(row["completed_at"]),
            notes=row["notes"],
        )

    def get(self, task_id: str) -> TenderTask | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tender_tasks WHERE task_id = ?", (str(task_id),)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_tender(self, tender_key: str) -> list[TenderTask]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tender_tasks WHERE tender_key = ? ORDER BY due_at, created_at, task_id",
                (str(tender_key),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_open(self, *, due_before: datetime | None = None) -> list[TenderTask]:
        sql = "SELECT * FROM tender_tasks WHERE status IN ('todo', 'in_progress')"
        params: list[str] = []
        if due_before is not None:
            sql += " AND due_at IS NOT NULL AND due_at <= ?"
            params.append(self._iso(due_before) or "")
        sql += " ORDER BY due_at, created_at, task_id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    def list_events(self, task_id: str) -> list[dict[str, object]]:
        """Return the immutable audit history of a task in chronological order."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, task_id, event_type, field_name, old_value, new_value, created_at
                FROM tender_task_events
                WHERE task_id = ?
                ORDER BY event_id
                """,
                (str(task_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, task_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tender_task_events WHERE task_id = ?", (str(task_id),))
            conn.execute("DELETE FROM tender_tasks WHERE task_id = ?", (str(task_id),))
            conn.commit()
