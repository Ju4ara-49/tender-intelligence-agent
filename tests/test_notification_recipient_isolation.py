from datetime import datetime

from src.models.tender import Tender
from src.notifications.telegram import TelegramNotifier
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState
from src.models.tender import TenderAnalysis


def test_notification_delivery_is_isolated_by_recipient(tmp_path) -> None:
    db = TenderDatabase(tmp_path / "notifications.db")
    state = NotificationDeliveryState(db)
    tender = Tender(
        platform="test",
        external_id="1",
        title="Tender",
        url="https://example.test/1",
        price=100,
        deadline=datetime(2030, 1, 1),
    )
    db.save_tender(tender)

    assert state.was_notified(tender, recipient_key="chat-a") is False
    assert state.was_notified(tender, recipient_key="chat-b") is False
    state.mark_notified(tender, recipient_key="chat-a")

    assert state.was_notified(tender, recipient_key="chat-a") is True
    assert state.was_notified(tender, recipient_key="chat-b") is False

    state.mark_notified(tender, recipient_key="chat-b")
    assert state.was_notified(tender, recipient_key="chat-b") is True


def test_telegram_notifier_uses_explicit_chat_override() -> None:
    notifier = TelegramNotifier(bot_token="token", chat_id="global-chat")
    calls: list[tuple[str, str | None]] = []

    def fake_send(text: str, chat_id: str | None = None) -> bool:
        calls.append((text, chat_id))
        return True

    notifier._send = fake_send  # type: ignore[method-assign]
    tender = Tender(
        platform="test",
        external_id="2",
        title="Tender",
        url="https://example.test/2",
        price=100,
        deadline=datetime(2030, 1, 1),
    )
    analysis = TenderAnalysis(
        relevance_score=90,
        summary="Подходит",
        recommendation="participate",
    )

    assert notifier.send_tender_alert(tender, analysis, chat_id="user-chat") is True
    assert len(calls) == 1
    assert calls[0][1] == "user-chat"

    calls.clear()
    assert notifier.send_tender_alert(tender, analysis) is True
    assert calls[0][1] == "global-chat"
