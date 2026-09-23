from datetime import datetime, timedelta, timezone

from src.models.tender import Tender, TenderAnalysis
from src.notifications.telegram import TelegramNotifier
from src.tenderplan import TenderTaskStore


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


def test_telegram_alert_does_not_create_application_task(tmp_path):
    store = TenderTaskStore(tmp_path / "tenders.db")
    notifier = TelegramNotifier(task_store=store, dry_run_when_no_token=True)
    tender = _tender(datetime.now(timezone.utc) + timedelta(days=10))

    assert notifier.send_tender_alert(tender, _analysis()) is False
    assert store.list_for_tender(tender.unique_key) == []
