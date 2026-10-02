"""Integration tests for Telegram notification and TenderPlan interaction.

The notifier must NOT create application tasks itself — task creation is the
responsibility of the CRM participation callback (``handle_callback`` for
``crm:participate:*``). These tests guard that separation of concerns.
"""
from __future__ import annotations

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


def test_telegram_alert_does_not_create_tasks(tmp_path):
    """send_tender_alert must be a pure notification — no task side-effects."""
    store = TenderTaskStore(tmp_path / "tenders.db")
    notifier = TelegramNotifier(task_store=store, dry_run_when_no_token=True)
    tender = _tender(datetime.now(timezone.utc) + timedelta(days=10))

    assert notifier.send_tender_alert(tender, _analysis()) is False

    assert store.list_for_tender(tender.unique_key) == []


def test_telegram_alert_creates_task_only_via_participate_callback(tmp_path):
    """Task creation must flow through the CRM participation callback, not the notifier."""
    from src.crm.telegram import handle_callback

    store = TenderTaskStore(tmp_path / "tasks.db")
    from src.storage.database import TenderDatabase

    db = TenderDatabase(tmp_path / "test.db")
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO tenders (platform, external_id, unique_key, title, url,
                                 first_seen_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("eis", "123", "eis:123", "Test", "https://x.test/1",
             "2026-09-13T00:00:00+00:00", "2026-09-13T00:00:00+00:00"),
        )
    tender_id = db.get_tender_id("eis:123")
    assert tender_id is not None

    notifier = TelegramNotifier(dry_run_when_no_token=True)

    class _Bot:
        def __init__(self):
            self.orchestrator = type("O", (), {"db": db, "task_store": store, "lifecycle_store": type("L", (), {
                "set": lambda *a, **kw: None,
                "ensure": lambda *a, **kw: None,
                "get": lambda *a, **kw: None,
                "history": lambda *a, **kw: [],
            })()})()
            self.sent = []

        @staticmethod
        def _keyboard():
            return {"keyboard": []}

        def _send(self, chat_id, text, reply_markup=None):
            self.sent.append((chat_id, text, reply_markup))

    bot = _Bot()
    assert handle_callback(bot, "100", f"crm:participate:eis:123") is True

    assert notifier.send_tender_alert(_tender(datetime.now(timezone.utc) + timedelta(days=10)), _analysis()) is False

    assert len(store.list_for_tender("eis:123")) == 1
