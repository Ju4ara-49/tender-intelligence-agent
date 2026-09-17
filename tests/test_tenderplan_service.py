from datetime import datetime, timezone
from pathlib import Path

from src.tenderplan import TaskStatus, TenderTaskStore, application_task_id, ensure_application_task


def test_application_task_id_is_stable_and_bounded():
    first = application_task_id("eis:123")
    second = application_task_id("eis:123")
    assert first == second
    assert first.startswith("application:")
    assert len(first) == len("application:") + 24


def test_ensure_application_task_is_idempotent(tmp_path: Path):
    store = TenderTaskStore(tmp_path / "agent.db")
    deadline = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)

    first = ensure_application_task(
        store,
        tender_key="eis:123",
        tender_title="Поставка запасных частей",
        deadline=deadline,
    )
    first.complete(datetime(2026, 9, 19, tzinfo=timezone.utc))
    store.save(first)

    second = ensure_application_task(
        store,
        tender_key="eis:123",
        tender_title="Обновлённое название",
        deadline=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )

    assert second.task_id == first.task_id
    assert second.status is TaskStatus.DONE
    assert second.due_at == deadline
    assert second.notes == "Поставка запасных частей"


def test_ensure_application_task_uses_tender_deadline(tmp_path: Path):
    store = TenderTaskStore(tmp_path / "agent.db")
    deadline = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)

    task = ensure_application_task(
        store,
        tender_key="b2b_center:42",
        tender_title="Поставка подшипников",
        deadline=deadline,
    )

    assert task.due_at == deadline
    assert task.title == "Подать заявку"
