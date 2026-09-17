"""TenderPlan task orchestration helpers."""

from __future__ import annotations

import hashlib
from datetime import datetime

from .storage import TenderTaskStore
from .tasks import TaskPriority, TenderTask


def application_task_id(tender_key: str) -> str:
    """Return a stable task id for the canonical application task of a tender."""
    digest = hashlib.sha256(str(tender_key).encode("utf-8")).hexdigest()[:24]
    return f"application:{digest}"


def ensure_application_task(
    store: TenderTaskStore,
    *,
    tender_key: str,
    tender_title: str,
    deadline: datetime | None,
    priority: TaskPriority = TaskPriority.NORMAL,
) -> TenderTask:
    """Create the default application task once and keep it idempotent.

    Existing task state is never overwritten: completing/cancelling/reassigning a
    task is a user decision and must survive later tender refreshes.
    """
    task_id = application_task_id(tender_key)
    existing = store.get(task_id)
    if existing is not None:
        return existing

    task = TenderTask(
        task_id=task_id,
        tender_key=tender_key,
        title="Подать заявку",
        due_at=deadline,
        priority=priority,
        notes=str(tender_title or "").strip(),
    )
    return store.save(task)
