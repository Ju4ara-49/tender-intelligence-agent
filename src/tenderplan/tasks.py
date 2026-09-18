"""Task domain for TenderPlan-style tender work management.

This module is deliberately persistence-agnostic: storage adapters can persist
TenderTask without coupling the domain object to SQLite or Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(slots=True)
class TenderTask:
    """A concrete action associated with one canonical tender identity."""

    task_id: str
    tender_key: str
    title: str
    user_id: str = ""
    due_at: datetime | None = None
    responsible: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.TODO
    created_at: datetime | None = None
    completed_at: datetime | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        self.task_id = str(self.task_id).strip()
        self.tender_key = str(self.tender_key).strip()
        self.title = str(self.title).strip()
        self.user_id = str(self.user_id).strip()
        self.responsible = str(self.responsible).strip()
        self.notes = str(self.notes).strip()
        if not self.task_id:
            raise ValueError("task_id is required")
        if not self.tender_key:
            raise ValueError("tender_key is required")
        if not self.title:
            raise ValueError("title is required")
        self.due_at = self._normalize_dt(self.due_at)
        self.created_at = self._normalize_dt(self.created_at) or datetime.now(timezone.utc)
        self.completed_at = self._normalize_dt(self.completed_at)
        if self.status == TaskStatus.DONE and self.completed_at is None:
            self.completed_at = self.created_at
        if self.status != TaskStatus.DONE and self.completed_at is not None:
            raise ValueError("completed_at is only valid for done tasks")

    @staticmethod
    def _normalize_dt(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @property
    def is_open(self) -> bool:
        return self.status in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}

    def is_overdue(self, now: datetime | None = None) -> bool:
        """Return true only for an open task whose deadline has passed."""
        if not self.is_open or self.due_at is None:
            return False
        current = self._normalize_dt(now) or datetime.now(timezone.utc)
        return self.due_at < current

    def days_until_due(self, now: datetime | None = None) -> int | None:
        """Whole calendar-day distance to the deadline; None means no deadline."""
        if self.due_at is None:
            return None
        current = self._normalize_dt(now) or datetime.now(timezone.utc)
        return (self.due_at.date() - current.date()).days

    def start(self) -> None:
        """Transition an open TODO task to active work."""
        if self.status != TaskStatus.TODO:
            raise ValueError(f"only todo task can be started, current status={self.status.value}")
        self.status = TaskStatus.IN_PROGRESS

    def complete(self, completed_at: datetime | None = None) -> None:
        """Transition an open task to done."""
        if self.status == TaskStatus.CANCELLED:
            raise ValueError("cancelled task cannot be completed")
        if self.status == TaskStatus.DONE:
            raise ValueError("done task is already completed")
        self.status = TaskStatus.DONE
        self.completed_at = self._normalize_dt(completed_at) or datetime.now(timezone.utc)

    def cancel(self) -> None:
        """Cancel the task without changing the tender identity."""
        if self.status == TaskStatus.DONE:
            raise ValueError("done task cannot be cancelled")
        self.status = TaskStatus.CANCELLED
        self.completed_at = None

    def reopen(self) -> None:
        """Return a completed or cancelled task to the TODO state."""
        if self.status not in {TaskStatus.DONE, TaskStatus.CANCELLED}:
            raise ValueError("only done or cancelled task can be reopened")
        self.status = TaskStatus.TODO
        self.completed_at = None

    def to_dict(self) -> dict[str, object]:
        """Serialize the task for APIs, Telegram payloads and audit logs."""
        return {
            "task_id": self.task_id,
            "tender_key": self.tender_key,
            "title": self.title,
            "user_id": self.user_id,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "responsible": self.responsible,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "notes": self.notes,
        }
