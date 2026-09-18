"""TenderPlan task orchestration helpers."""

from __future__ import annotations

import hashlib
from datetime import datetime

from .storage import TenderTaskStore
from .tasks import TaskPriority, TenderTask


def application_task_id(tender_key: str, user_id: str | int | None = None) -> str:
    """Return a stable task id scoped to a user when user_id is provided."""
    identity = str(tender_key) if user_id is None else f"{str(user_id).strip()}\0{str(tender_key)}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"application:{digest}"


def ensure_application_task(
    store: TenderTaskStore,
    *,
    tender_key: str,
    tender_title: str,
    user_id: str | int | None = None,
    deadline: datetime | None,
    priority: TaskPriority = TaskPriority.NORMAL,
) -> TenderTask:
    """Create or synchronize the canonical application task for a tender.

    User-controlled state (status, responsible, priority and notes) is preserved.
    The tender deadline remains source-of-truth and is synchronized when it changes;
    the storage adapter records that change in the immutable task history.
    """
    task_id = application_task_id(tender_key, user_id)
    owner = "" if user_id is None else str(user_id).strip()
    existing = store.get(task_id, user_id=owner if user_id is not None else None)
    if existing is not None:
        if existing.due_at != deadline:
            existing.due_at = deadline
            store.save(existing)
        return existing

    task = TenderTask(
        task_id=task_id,
        tender_key=tender_key,
        title="Подать заявку",
        user_id=owner,
        due_at=deadline,
        priority=priority,
        notes=str(tender_title or "").strip(),
    )
    return store.save(task)


def task_priority_for_deadline(deadline: datetime | None) -> TaskPriority:
    """Derive a default urgency from the tender application deadline."""
    if deadline is None:
        return TaskPriority.NORMAL
    from datetime import datetime, timezone
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    else:
        deadline = deadline.astimezone(timezone.utc)
    remaining = deadline - datetime.now(timezone.utc)
    if remaining.total_seconds() <= 3 * 86400:
        return TaskPriority.CRITICAL
    if remaining.total_seconds() <= 7 * 86400:
        return TaskPriority.HIGH
    return TaskPriority.NORMAL
