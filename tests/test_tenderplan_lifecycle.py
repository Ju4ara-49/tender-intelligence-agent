from datetime import datetime, timezone

import pytest

from src.tenderplan import TaskStatus, TenderTask


def _task() -> TenderTask:
    return TenderTask(task_id="t1", tender_key="eis:1", title="Подать заявку")


def test_start_moves_todo_to_in_progress():
    task = _task()
    task.start()
    assert task.status is TaskStatus.IN_PROGRESS
    assert task.is_open is True


def test_start_rejects_non_todo_task():
    task = _task()
    task.start()
    with pytest.raises(ValueError, match="only todo task"):
        task.start()


def test_done_task_cannot_be_completed_twice():
    task = _task()
    task.complete(datetime(2026, 9, 18, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="already completed"):
        task.complete()


def test_reopen_clears_terminal_state():
    task = _task()
    task.complete(datetime(2026, 9, 18, tzinfo=timezone.utc))
    task.reopen()
    assert task.status is TaskStatus.TODO
    assert task.completed_at is None


def test_reopen_cancelled_task():
    task = _task()
    task.cancel()
    task.reopen()
    assert task.status is TaskStatus.TODO


def test_reopen_rejects_open_task():
    task = _task()
    with pytest.raises(ValueError, match="done or cancelled"):
        task.reopen()


def test_to_dict_contains_api_safe_values():
    task = TenderTask(
        task_id="t1",
        tender_key="eis:1",
        title="Подать заявку",
        due_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )
    payload = task.to_dict()
    assert payload["task_id"] == "t1"
    assert payload["tender_key"] == "eis:1"
    assert payload["status"] == "todo"
    assert payload["due_at"] == "2026-09-20T12:00:00+00:00"


def test_tender_lifecycle_happy_path_is_explicit():
    from src.tenderplan import TenderLifecycleStatus, can_transition, transition
    status = TenderLifecycleStatus.DISCOVERED
    for target in (
        TenderLifecycleStatus.RELEVANT,
        TenderLifecycleStatus.SHORTLISTED,
        TenderLifecycleStatus.ASSIGNED,
        TenderLifecycleStatus.PREPARING,
        TenderLifecycleStatus.SUBMITTED,
        TenderLifecycleStatus.AUCTION,
        TenderLifecycleStatus.WON,
        TenderLifecycleStatus.ARCHIVED,
    ):
        assert can_transition(status, target)
        status = transition(status, target)
    assert status is TenderLifecycleStatus.ARCHIVED


def test_tender_lifecycle_rejects_invalid_jump_and_archive_reentry():
    from src.tenderplan import InvalidLifecycleTransition, TenderLifecycleStatus, transition
    with pytest.raises(InvalidLifecycleTransition):
        transition(TenderLifecycleStatus.DISCOVERED, TenderLifecycleStatus.SUBMITTED)
    with pytest.raises(InvalidLifecycleTransition):
        transition(TenderLifecycleStatus.ARCHIVED, TenderLifecycleStatus.RELEVANT)


def test_tender_lifecycle_terminal_states_archive_only():
    from src.tenderplan import TERMINAL_STATUSES, TenderLifecycleStatus, can_transition
    for status in TERMINAL_STATUSES:
        if status is TenderLifecycleStatus.ARCHIVED:
            assert not can_transition(status, TenderLifecycleStatus.RELEVANT)
        else:
            assert can_transition(status, TenderLifecycleStatus.ARCHIVED)


def test_crm_status_mapping_is_explicit():
    from src.tenderplan import TenderLifecycleStatus, lifecycle_from_crm
    assert lifecycle_from_crm("new") is TenderLifecycleStatus.DISCOVERED
    assert lifecycle_from_crm("docs_preparation") is TenderLifecycleStatus.PREPARING
    assert lifecycle_from_crm("waiting_result") is TenderLifecycleStatus.SUBMITTED
    assert lifecycle_from_crm("skipped") is TenderLifecycleStatus.REJECTED
    assert lifecycle_from_crm(" SUBMITTED ") is TenderLifecycleStatus.SUBMITTED


def test_unknown_crm_status_is_rejected():
    from src.tenderplan import lifecycle_from_crm
    with pytest.raises(ValueError):
        lifecycle_from_crm("unknown-status")
