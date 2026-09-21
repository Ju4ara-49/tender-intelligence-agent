from datetime import datetime, timezone

import pytest

from src.tenderplan.tasks import TaskPriority, TaskStatus, TenderTask


UTC = timezone.utc


def test_task_normalizes_naive_deadline_to_utc():
    task = TenderTask(
        task_id="t1",
        tender_key="eis:123",
        title="Проверить документацию",
        due_at=datetime(2026, 9, 20, 12, 0),
    )

    assert task.due_at == datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    assert task.created_at.tzinfo is UTC
    assert task.is_open is True


def test_overdue_only_for_open_task():
    now = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    task = TenderTask(
        task_id="t1",
        tender_key="eis:123",
        title="Подать заявку",
        due_at=datetime(2026, 9, 17, 12, 0, tzinfo=UTC),
    )

    assert task.is_overdue(now) is True
    task.complete(now)
    assert task.is_overdue(now) is False


def test_days_until_due_is_calendar_based():
    now = datetime(2026, 9, 18, 23, 59, tzinfo=UTC)
    task = TenderTask(
        task_id="t1",
        tender_key="b2b_center:42",
        title="Проверить обеспечение",
        due_at=datetime(2026, 9, 20, 1, 0, tzinfo=UTC),
    )

    assert task.days_until_due(now) == 2


def test_complete_sets_status_and_completion_time():
    completed = datetime(2026, 9, 18, 15, 0, tzinfo=UTC)
    task = TenderTask(
        task_id="t1",
        tender_key="rts:42",
        title="Назначить ответственного",
        priority=TaskPriority.HIGH,
    )

    task.complete(completed)

    assert task.status is TaskStatus.DONE
    assert task.completed_at == completed
    assert task.is_open is False


def test_cancelled_task_cannot_be_completed():
    task = TenderTask(
        task_id="t1",
        tender_key="tmk:42",
        title="Проверить условия",
    )
    task.cancel()

    assert task.status is TaskStatus.CANCELLED
    with pytest.raises(ValueError, match="cancelled task"):
        task.complete()


def test_done_task_cannot_be_cancelled():
    task = TenderTask(
        task_id="t1",
        tender_key="rosatom:42",
        title="Подготовить заявку",
    )
    task.complete(datetime(2026, 9, 18, tzinfo=UTC))

    with pytest.raises(ValueError, match="done task"):
        task.cancel()


def test_required_identity_fields_are_enforced():
    with pytest.raises(ValueError, match="task_id"):
        TenderTask(task_id="", tender_key="eis:1", title="x")
    with pytest.raises(ValueError, match="tender_key"):
        TenderTask(task_id="1", tender_key="", title="x")
    with pytest.raises(ValueError, match="title"):
        TenderTask(task_id="1", tender_key="eis:1", title="")


def test_completed_at_cannot_be_set_for_open_task():
    with pytest.raises(ValueError, match="completed_at"):
        TenderTask(
            task_id="t1",
            tender_key="eis:1",
            title="x",
            completed_at=datetime(2026, 9, 18, tzinfo=UTC),
        )
