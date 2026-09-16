import pytest

from src.notifications.telegram import TelegramNotifier


def test_send_text_without_credentials_respects_dry_run() -> None:
    notifier = TelegramNotifier(dry_run_when_no_token=True)

    assert notifier.send_text("test") is False


def test_send_text_without_credentials_can_fail_closed() -> None:
    notifier = TelegramNotifier(dry_run_when_no_token=False)

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        notifier.send_text("test")
