from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.models.tender import Tender, TenderAnalysis
from src.orchestrator import Orchestrator
from src.tenderplan import TenderTaskStore, application_task_id


def _orchestrator(tmp_path: Path, notifier) -> Orchestrator:
    obj = Orchestrator.__new__(Orchestrator)
    obj.task_store = TenderTaskStore(tmp_path / "agent.db")
    obj.notifier = notifier
    obj.notification_state = SimpleNamespace(mark_notified=lambda *args, **kwargs: None)
    return obj


def _tender() -> Tender:
    return Tender(
        platform="eis",
        external_id="123",
        title="Поставка запасных частей",
        url="https://example.test/123",
        deadline=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
    )


def _analysis() -> TenderAnalysis:
    return TenderAnalysis(
        relevance_score=90,
        summary="ok",
        recommendation="participate",
    )


def test_tenderplan_task_is_created_without_telegram(tmp_path: Path):
    obj = _orchestrator(tmp_path, notifier=SimpleNamespace())
    tender = _tender()

    obj._ensure_tenderplan_task(tender)

    task = obj.task_store.get(application_task_id(tender.unique_key))
    assert task is not None
    assert task.tender_key == tender.unique_key


def test_telegram_failure_does_not_remove_tenderplan_task(tmp_path: Path):
    class FailingNotifier:
        def send_tender_alert(self, *args, **kwargs):
            raise RuntimeError("telegram unavailable")

    obj = _orchestrator(tmp_path, notifier=FailingNotifier())
    tender = _tender()
    obj._ensure_tenderplan_task(tender)

    sent = obj._notify_and_record(
        tender,
        _analysis(),
        chat_id="123",
        recipient_key="user:123",
    )

    assert sent is False
    assert obj.task_store.get(application_task_id(tender.unique_key)) is not None


def test_successful_notification_keeps_single_idempotent_task(tmp_path: Path):
    class WorkingNotifier:
        def send_tender_alert(self, *args, **kwargs):
            return True

    obj = _orchestrator(tmp_path, notifier=WorkingNotifier())
    tender = _tender()

    obj._ensure_tenderplan_task(tender)
    obj._ensure_tenderplan_task(tender)
    assert len(obj.task_store.list_for_tender(tender.unique_key)) == 1

    assert obj._notify_and_record(
        tender,
        _analysis(),
        chat_id="123",
        recipient_key="user:123",
    )
