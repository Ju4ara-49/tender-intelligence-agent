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

    def complete(self, completed_at: datetime | None = None) -> None:
        """Transition an open task to done."""
        if self.status == TaskStatus.CANCELLED:
            raise ValueError("cancelled task cannot be completed")
        self.status = TaskStatus.DONE
        self.completed_at = self._normalize_dt(completed_at) or datetime.now(timezone.utc)

    def cancel(self) -> None:
        """Cancel the task without changing the tender identity."""
        if self.status == TaskStatus.DONE:
            raise ValueError("done task cannot be cancelled")
        self.status = TaskStatus.CANCELLED
        self.completed_at = None
