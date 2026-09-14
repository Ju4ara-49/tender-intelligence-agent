from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.crm.telegram import handle_callback
from src.models.tender import Tender, TenderAnalysis
from src.notifications.telegram import TelegramNotifier


class _FakeBoard:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def set_status(self, tender_id: int, status: str):
        self.calls.append((tender_id, status))
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
        self.assertEqual(bot.crm_board.calls, [(42, "participating")])
        self.assertIn("Статус тендера #42 изменён", bot.sent[-1][1])

    def test_notification_keeps_russian_recommendation(self) -> None:
        analysis = TenderAnalysis(
            relevance_score=90,
            summary="Подходит",
            recommendation="participate",
        )
        text = TelegramNotifier.format_message(self._tender(), analysis)
        self.assertIn("Рекомендация:", text)
        self.assertIn("Участвовать", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
