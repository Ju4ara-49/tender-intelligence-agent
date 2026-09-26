from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.crm.telegram import handle_callback
from src.models.tender import Tender, TenderAnalysis
from src.notifications.telegram import TelegramNotifier
from src.storage.database import TenderDatabase
from src.telegram_multiuser import MultiUserTelegramBot


class _FakeBoard:
    def __init__(self) -> None:
        self.calls = []
        self._status = "new"

    def get_status(self, tender_id: int) -> str:
        return self._status

    def set_status(self, tender_id: int, status: str, *, force: bool = False) -> str:
        self.calls.append((tender_id, status, force))
        self._status = status
        return status

    def entry(self, tender_id: int):
        return SimpleNamespace(tender_id=tender_id, status="new", assignee="", labels=[], updated_at="")


class _DbWithBoard:
    """Реальный TenderDatabase + TenderBoard, чтобы callback менял фактический статус."""

    def __init__(self, db) -> None:
        self._db = db

    def get_tender_id(self, unique_key: str):
        return self._db.get_tender_id(unique_key)

    @property
    def crm_board(self):
        return TenderBoard(self._db)


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
    def test_participate_callback_does_not_resurrect_terminal_status(self) -> None:
        """Regression: кнопка УЧАСТВОВАТЬ не должна воскрешать won/lost/skipped.

        Единый контракт P1: participate идёт только по ALLOWED_TRANSITIONS
        (без force=True), поэтому терминальный статус вызывает
        InvalidStatusTransition и остаётся неизменным.
        """
        db = TenderDatabase(Path(tempfile.mkdtemp()) / "terminal_crm.db")
        tender_id = db.save_tender(Tender(platform="eis", external_id="TERM-1", title="Terminal", url="https://example.test/t"))
        from src.storage import STATUS_LOST, STATUS_SKIPPED, STATUS_WON, TenderBoard

        for status in (STATUS_WON, STATUS_LOST, STATUS_SKIPPED):
            with self.subTest(status=status):
                board = TenderBoard(db)
                board.set_status(tender_id, status, force=True)
                bot = _FakeBot()
                bot.crm_board = TenderBoard(db)
                bot.orchestrator.db = _DbWithBoard(db)
                self.assertTrue(handle_callback(bot, "100", "crm:participate:eis:TERM-1"))
                self.assertEqual(TenderBoard(db).get_status(tender_id), status)
                refusal = bot.messages[-1][1]
                # The callback reports the refusal through html.escape, so
                # single quotes arrive as &#x27;.
                self.assertIn("Cannot move tender", refusal)
                self.assertIn(
                    f"from &#x27;{status}&#x27; to &#x27;participating&#x27;",
                    refusal,
                )

    def test_participate_callback_changes_crm_status(self) -> None:
        bot = _FakeBot()
        self.assertTrue(handle_callback(bot, "100", "crm:participate:eis:1234567890"))
        # No force bypass: the callback must move the board only through the
        # ALLOWED_TRANSITIONS state machine (force is never requested).
        self.assertEqual(bot.crm_board.calls, [(42, "participating", False)])
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

    def test_removing_user_stops_active_search_before_access_is_revoked(self) -> None:
        bot = object.__new__(MultiUserTelegramBot)
        bot._allowed_user_ids = {"838120236", "42"}
        bot._whitelist_lock = __import__("threading").Lock()
        bot._search_lock = __import__("threading").Lock()
        bot._admin_waiting = {"838120236": "remove"}
        bot._send = lambda *args, **kwargs: None

        class FakeOrchestrator:
            def __init__(self):
                self.stop_calls = 0

            def request_stop(self):
                self.stop_calls += 1

        orchestrator = FakeOrchestrator()
        bot._user_orchestrators = {"42": orchestrator}

        with tempfile.TemporaryDirectory() as tmp:
            whitelist = Path(tmp) / "telegram_allowed_users.json"
            with patch("src.telegram_multiuser.WHITELIST_FILE", whitelist):
                bot._remove_user("838120236", "42")
            self.assertEqual(orchestrator.stop_calls, 1)
            self.assertNotIn("42", bot._allowed_user_ids)
            self.assertEqual(__import__("json").loads(whitelist.read_text(encoding="utf-8")), [])

    def test_revoked_user_receives_no_post_search_results(self) -> None:
        bot = object.__new__(MultiUserTelegramBot)
        bot._send_messages = []
        bot._send = lambda chat_id, text, reply_markup=None: bot._send_messages.append(text)
        bot._keyboard = lambda: {}
        bot._search_lock = __import__("threading").Lock()
        bot._search_threads = {}
        bot._user_orchestrators = {}
        allowed_checks = 0

        def is_allowed(_chat_id):
            nonlocal allowed_checks
            allowed_checks += 1
            return False

        bot._is_allowed = is_allowed

        class FakeOrchestrator:
            stop_requested = False
            last_run_results = [Tender(platform="eis", external_id="1", title="must not be sent", url="https://example.test/1")]

            def run_cycle_for_user(self, chat_id):
                return [{"search_number": 1, "found": 1, "filtered": 1, "new": 1}]

        bot._run_search_for_user("42", FakeOrchestrator())
        self.assertEqual(len(bot._send_messages), 1)
        self.assertIn("Поиск выполняется", bot._send_messages[0])
        self.assertGreaterEqual(allowed_checks, 1)
        self.assertNotIn("must not be sent", "\n".join(bot._send_messages))

    def test_whitelist_file_is_resolved_from_project_root(self) -> None:
        source = __import__("pathlib").Path(__import__("src.telegram_multiuser", fromlist=["MultiUserTelegramBot"]).__file__).read_text(encoding="utf-8")
        self.assertIn("WHITELIST_FILE = PROJECT_ROOT / \"data\" / \"telegram_allowed_users.json\"", source)


    def test_notifier_does_not_create_tenderplan_tasks(self) -> None:
        from pathlib import Path
        from src.tenderplan import TenderTaskStore

        store = TenderTaskStore(Path(tempfile.mkdtemp()) / "tasks.db")
        notifier = TelegramNotifier(task_store=store)
        tender = Tender(platform="eis", external_id="task-guard", title="Test", url="https://example.test/tender")
        analysis = TenderAnalysis(relevance_score=80, recommendation="participate", summary="ok")

        notifier.send_tender_alert(tender, analysis)

        self.assertEqual(store.list_for_tender(tender.unique_key), [])


if __name__ == "__main__":
    unittest.main()
