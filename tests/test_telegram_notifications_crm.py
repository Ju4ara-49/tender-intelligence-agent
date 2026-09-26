from __future__ import annotations

import unittest
from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import patch

from src.crm.telegram import handle_callback
from src.models.tender import Tender, TenderAnalysis
from src.notifications.telegram import TelegramNotifier


class _FakeBoard:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, bool]] = []
        self._status = "new"

    def get_status(self, tender_id: int) -> str:
        return self._status

    def set_status(self, tender_id: int, status: str, *, force: bool = False):
        self.calls.append((tender_id, status, force))
        self._status = status
        return status


class _FakeBot:
    def __init__(self) -> None:
        self.crm_board = _FakeBoard()
        self.orchestrator = SimpleNamespace(db=SimpleNamespace(get_tender_id=lambda key: 42 if key == "eis:12345" else None))
        self.sent: list[tuple[str, str]] = []

    @staticmethod
    def _keyboard() -> dict:
        return {"keyboard": []}

    def _send(self, chat_id: str, text: str, reply_markup=None):
        self.sent.append((chat_id, text))


class _FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class _FakeHttpClient:
    def __init__(self, response: _FakeHttpResponse) -> None:
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, *args, **kwargs):
        return self.response


class TelegramNotificationCrmTests(unittest.TestCase):
    def _tender(self) -> Tender:
        return Tender(
            platform="eis",
            external_id="12345",
            title="Поставка подшипников",
            url="https://example.test/tender/12345",
        )

    def test_participate_button_uses_tender_key_without_db_id(self) -> None:
        keyboard = TelegramNotifier._tender_keyboard(self._tender(), None)
        button = keyboard["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "УЧАСТВОВАТЬ")
        self.assertEqual(button["callback_data"], "crm:participate:eis:12345")
        self.assertLessEqual(len(button["callback_data"].encode("utf-8")), 64)

    def test_participate_callback_moves_crm_status(self) -> None:
        bot = _FakeBot()
        handled = handle_callback(bot, "777", "crm:participate:eis:12345")
        self.assertTrue(handled)
        self.assertEqual(bot.crm_board.calls, [(42, "participating", False)])
        self.assertIn("Статус тендера #42 изменён", bot.sent[-1][1])

    def test_notification_shows_start_end_and_deadline_dates(self) -> None:
        tender = self._tender()
        tender.start_date = datetime(2026, 9, 1, tzinfo=timezone.utc)
        tender.end_date = datetime(2026, 9, 20, tzinfo=timezone.utc)
        tender.deadline = datetime(2026, 9, 15, tzinfo=timezone.utc)
        analysis = TenderAnalysis(relevance_score=90, summary="Подходит", recommendation="participate")
        text = TelegramNotifier.format_message(tender, analysis)
        self.assertIn("Дата начала:", text)
        self.assertIn("01.09.2026", text)
        self.assertIn("Дата окончания:", text)
        self.assertIn("20.09.2026", text)
        self.assertIn("Срок подачи:", text)
        self.assertIn("15.09.2026", text)

    def test_notification_keeps_russian_recommendation(self) -> None:
        analysis = TenderAnalysis(relevance_score=90, summary="Подходит", recommendation="participate")
        text = TelegramNotifier.format_message(self._tender(), analysis)
        self.assertIn("Рекомендация:", text)
        self.assertIn("Участвовать", text)

    def test_telegram_api_ok_false_is_delivery_failure(self) -> None:
        notifier = TelegramNotifier(bot_token="token", chat_id="42", dry_run_when_no_token=False)
        response = _FakeHttpResponse({"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})
        with patch("src.notifications.telegram.httpx.Client", return_value=_FakeHttpClient(response)):
            self.assertFalse(notifier.send_text("test"))

    def test_telegram_api_ok_true_is_delivery_success(self) -> None:
        notifier = TelegramNotifier(bot_token="token", chat_id="42", dry_run_when_no_token=False)
        response = _FakeHttpResponse({"ok": True, "result": {"message_id": 1}})
        with patch("src.notifications.telegram.httpx.Client", return_value=_FakeHttpClient(response)):
            self.assertTrue(notifier.send_text("test"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
