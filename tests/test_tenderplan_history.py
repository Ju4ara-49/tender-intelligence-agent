from datetime import datetime, timedelta, timezone

from src.tenderplan import TaskPriority, TenderTask, TenderTaskStore


def test_task_history_records_creation_status_assignment_and_deadline_changes(tmp_path):
    store = TenderTaskStore(tmp_path / "tenders.db")
    task = TenderTask(
        task_id="application:test-history",
        tender_key="eis:history-1",
        title="Подать заявку",
        due_at=datetime.now(timezone.utc) + timedelta(days=10),
    )

    store.save(task)
    task.responsible = "Иван"
    task.priority = TaskPriority.HIGH
    task.start()
    task.due_at = datetime.now(timezone.utc) + timedelta(days=2)
    store.save(task)

    events = store.list_events(task.task_id)
    assert events[0]["event_type"] == "created"
    changed = {(event["event_type"], event["field_name"]) for event in events[1:]}
    assert ("field_changed", "responsible") in changed
    assert ("field_changed", "priority") in changed
    assert ("status_changed", "status") in changed
    assert ("field_changed", "due_at") in changed


def test_delete_removes_task_and_its_history(tmp_path):
    store = TenderTaskStore(tmp_path / "tenders.db")
    task = TenderTask(
        task_id="application:delete-history",
        tender_key="eis:delete-1",
        title="Подать заявку",
    )
    store.save(task)
    assert store.list_events(task.task_id)

    store.delete(task.task_id)

    assert store.get(task.task_id) is None
    assert store.list_events(task.task_id) == []
