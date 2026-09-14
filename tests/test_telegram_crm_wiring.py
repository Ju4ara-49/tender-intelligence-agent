from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.crm.telegram import handle_callback
from src.models.tender import Tender, TenderAnalysis
from src.notifications.telegram import TelegramNotifier
from src.telegram_multiuser import MultiUserTelegramBot


class _FakeBoard:
    def __init__(self) -> None:
        self.calls = []

    def set_status(self, tender_id: int, status: str, *, force: bool = False) -> str:
        self.calls.append((tender_id, status, force))
        return status

    def entry(self, tender_id: int):
        return SimpleNamespace(tender_id=tender_id, status="new", assignee="", labels=[], updated_at="")


class _FakeBot:
    def __init__(self) -> None:
        self.orchestrator = SimpleNamespace(db=SimpleNamespace(get_tender_id=lambda key: 42))
        self.messages = []
        self.crm_board = _FakeBoard()

    def _send(self, chat_id, text, reply_markup=None):
        self.messages.append((chat_id, text, reply_markup))

    def _keyboard(self):
        return {}


class TelegramCrmWiringTests(unittest.TestCase):
    def test_participate_callback_changes_crm_status(self) -> None:
        bot = _FakeBot()
        self.assertTrue(handle_callback(bot, "100", "crm:participate:eis:1234567890"))
        self.assertEqual(bot.crm_board.calls, [(42, "participating", True)])
        self.assertIn("Участвуем", bot.messages[-1][1])

    def test_notifier_emits_participation_callback_without_db_id(self) -> None:
        tender = Tender(platform="eis", external_id="1234567890", title="Test", url="https://example.test/tender")
        analysis = TenderAnalysis(relevance_score=80, recommendation="participate", summary="ok")
        markup = TelegramNotifier._tender_keyboard(tender, None)
        callback = markup["inline_keyboard"][0][0]["callback_data"]
        self.assertEqual(callback, "crm:participate:eis:1234567890")
        self.assertEqual(markup["inline_keyboard"][0][0]["text"], "УЧАСТВОВАТЬ")
        self.assertLessEqual(len(callback.encode("utf-8")), 64)

    def test_main_bot_wires_crm_handlers(self) -> None:
        source = __import__("pathlib").Path(__import__("src.telegram_bot", fromlist=["TelegramBot"]).__file__).read_text(encoding="utf-8")
        self.assertIn("handle_crm_callback", source)
        self.assertIn("handle_crm_message", source)
        self.assertIn('data.startswith("crm:")', source)
        self.assertIn("handle_crm_message(self, chat_id, text)", source)

    def test_multiuser_search_uses_profile_runtime(self) -> None:
        stats = MultiUserTelegramBot._aggregate_profile_stats(
            [
                {"search_number": 10, "found": 5, "filtered": 2, "notified": 1, "platform_errors": 1},
                {"search_number": 11, "found": 7, "filtered": 3, "notified": 2, "platform_errors": 0},
            ]
        )
        self.assertEqual(stats["profile_count"], 2)
        self.assertEqual(stats["search_number"], 11)
        self.assertEqual(stats["found"], 12)
        self.assertEqual(stats["filtered"], 5)
        self.assertEqual(stats["notified"], 3)
        self.assertEqual(stats["platform_errors"], 1)

        source = __import__("pathlib").Path(__import__("src.telegram_multiuser", fromlist=["MultiUserTelegramBot"]).__file__).read_text(encoding="utf-8")
        self.assertIn("orchestrator.run_cycle_for_user(chat_id)", source)


if __name__ == "__main__":
    unittest.main()
