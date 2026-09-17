from datetime import datetime, timedelta, timezone

from src.models.tender import Tender, TenderAnalysis
from src.notifications.telegram import TelegramNotifier
from src.tenderplan import TaskPriority, TenderTaskStore


def _tender(deadline: datetime) -> Tender:
    return Tender(
        platform="eis",
        external_id="123",
        title="Поставка запасных частей",
        url="https://example.test/tender/123",
        deadline=deadline,
    )


def _analysis() -> TenderAnalysis:
    return TenderAnalysis(
        relevance_score=95,
        summary="Подходит",
        recommendation="participate",
    )


def test_telegram_alert_creates_application_task_in_dry_run(tmp_path):
    store = TenderTaskStore(tmp_path / "tenders.db")
    notifier = TelegramNotifier(task_store=store, dry_run_when_no_token=True)
    tender = _tender(datetime.now(timezone.utc) + timedelta(days=10))

    assert notifier.send_tender_alert(tender, _analysis()) is False

    task = store.get("application:" + __import__("hashlib").sha256(tender.unique_key.encode()).hexdigest()[:24])
    assert task is not None
    assert task.tender_key == tender.unique_key
    assert task.title == "Подать заявку"
    assert task.priority is TaskPriority.NORMAL
    assert task.due_at == tender.deadline


def test_telegram_alert_preserves_existing_task_state_and_updates_priority_only_on_creation(tmp_path):
    store = TenderTaskStore(tmp_path / "tenders.db")
    notifier = TelegramNotifier(task_store=store, dry_run_when_no_token=True)
    tender = _tender(datetime.now(timezone.utc) + timedelta(days=2))

    notifier.send_tender_alert(tender, _analysis())
    task = store.list_for_tender(tender.unique_key)[0]
    assert task.priority is TaskPriority.CRITICAL

    task.responsible = "Иван"
    task.notes = "Моя заметка"
    task.start()
    store.save(task)

    tender.deadline = datetime.now(timezone.utc) + timedelta(days=20)
    notifier.send_tender_alert(tender, _analysis())

    restored = store.get(task.task_id)
    assert restored is not None
    assert restored.status.value == "in_progress"
    assert restored.responsible == "Иван"
    assert restored.notes == "Моя заметка"
    assert restored.priority is TaskPriority.CRITICAL
