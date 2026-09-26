from datetime import datetime, timezone
from pathlib import Path

from src.tenderplan import TaskPriority, TaskStatus, TenderTask, TenderTaskStore


def test_task_store_round_trip(tmp_path: Path):
    store = TenderTaskStore(tmp_path / "agent.db")
    created = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)
    due = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    task = TenderTask(
        task_id="task-1",
        tender_key="eis:123",
        title="Подать заявку",
        due_at=due,
        responsible="manager-1",
        priority=TaskPriority.HIGH,
        created_at=created,
        notes="Проверить обеспечение",
    )

    store.save(task)
    loaded = store.get("task-1")

    assert loaded == task
    assert loaded.due_at == due
    assert loaded.priority is TaskPriority.HIGH


def test_task_store_upsert_preserves_latest_state(tmp_path: Path):
    store = TenderTaskStore(tmp_path / "agent.db")
    task = TenderTask(
        task_id="task-1",
        tender_key="b2b_center:42",
        title="Проверить документы",
    )
    store.save(task)

    task.complete(datetime(2026, 9, 18, 15, 0, tzinfo=timezone.utc))
    store.save(task)

    loaded = store.get("task-1")
    assert loaded is not None
    assert loaded.status is TaskStatus.DONE
    assert loaded.completed_at == datetime(2026, 9, 18, 15, 0, tzinfo=timezone.utc)


def test_task_store_lists_tender_tasks_in_due_order(tmp_path: Path):
    store = TenderTaskStore(tmp_path / "agent.db")
    store.save(
        TenderTask(
            task_id="late",
            tender_key="eis:1",
            title="Поздняя задача",
            due_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
        )
    )
    store.save(
        TenderTask(
            task_id="early",
            tender_key="eis:1",
            title="Ранняя задача",
            due_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        )
    )

    tasks = store.list_for_tender("eis:1")

    assert [task.task_id for task in tasks] == ["early", "late"]


def test_task_store_open_due_filter_excludes_done_tasks(tmp_path: Path):
    store = TenderTaskStore(tmp_path / "agent.db")
    due = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    open_task = TenderTask(task_id="open", tender_key="eis:1", title="Открытая", due_at=due)
    done_task = TenderTask(task_id="done", tender_key="eis:2", title="Закрытая", due_at=due)
    done_task.complete(datetime(2026, 9, 17, tzinfo=timezone.utc))
    store.save(open_task)
    store.save(done_task)

    tasks = store.list_open(due_before=datetime(2026, 9, 19, tzinfo=timezone.utc))

    assert [task.task_id for task in tasks] == ["open"]


def test_task_store_missing_returns_none(tmp_path: Path):
    store = TenderTaskStore(tmp_path / "agent.db")
    assert store.get("missing") is None


def test_task_store_isolates_same_tender_between_users(tmp_path: Path):
    store = TenderTaskStore(tmp_path / "agent.db")
    store.save(TenderTask(task_id="u1-task", tender_key="eis:1", title="Задача 1", user_id="u1"))
    store.save(TenderTask(task_id="u2-task", tender_key="eis:1", title="Задача 2", user_id="u2"))

    assert [task.task_id for task in store.list_for_tender("eis:1", user_id="u1")] == ["u1-task"]
    assert [task.task_id for task in store.list_for_tender("eis:1", user_id="u2")] == ["u2-task"]
    assert store.get("u1-task", user_id="u2") is None
