from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import src.orchestrator as orchestrator_module
from src.models.tender import Tender
from src.orchestrator import Orchestrator
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState
from src.telegram_settings import TenderCriteria


class _FakeNotifier:
    def __init__(self, result: bool = False):
        self.result = result
        self.calls = 0
        self.chat_id = None

    def send_tender_alert(self, tender, analysis, chat_id=None):
        self.calls += 1
        return self.result


class _FakeEmailNotifier:
    def send_excel(self, path, search_number):
        return None


class _FakeAnalyzer:
    def __init__(self, *, score=90, error=None):
        self.score = score
        self.error = error
        self.calls = 0

    def analyze(self, tender):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(relevance_score=self.score)


def _make_orchestrator(tmp_path, analyzer, notifier):
    db = TenderDatabase(tmp_path / "claims.db")
    state = NotificationDeliveryState(db)
    tender = Tender(
        platform="test",
        external_id="claim-1",
        title="Поставка подшипников",
        description="Подробное описание закупки подшипников",
        url="https://example.test/claim-1",
        price=100000.0,
        deadline=datetime.now(timezone.utc) + timedelta(days=20),
        application_security_percent=1.0,
    )
    collector = SimpleNamespace(
        platform="test",
        config={"lookback_days": 3},
        search=lambda keywords, since: [tender],
        get_details=lambda external_id: deepcopy(tender),
    )
    settings = SimpleNamespace(
        config={
            "filters": {"min_text_length": 1},
            "search": {"platform_workers": 1},
            "collectors": {"test": {"lookback_days": 3}},
            "export": {"output_dir": str(tmp_path / "output")},
        },
        include_keywords=["подшипников"],
    )
    runner = Orchestrator.__new__(Orchestrator)
    runner.settings = settings
    runner.db = db
    runner.notification_state = state
    runner.criteria_store = SimpleNamespace(get=lambda user_id: TenderCriteria(min_submission_days=0))
    runner.profile_store = SimpleNamespace()
    runner.analyzer = analyzer
    runner.notifier = notifier
    runner.email_notifier = _FakeEmailNotifier()
    runner._stop_requested = False
    runner.last_run_results = []
    runner._get_next_search_number = lambda: 1
    runner.db.save_analysis = lambda *args, **kwargs: None
    return runner, collector, tender, db


def _claim_count(db):
    with db._connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM notification_delivery_claims").fetchone()[0]


def _run(monkeypatch, runner, collector):
    monkeypatch.setattr(orchestrator_module, "get_enabled_collectors", lambda config, enabled_platforms=None: [collector])
    monkeypatch.setattr(orchestrator_module, "export_tenders_to_excel", lambda *args, **kwargs: args[1])
    return runner.run_cycle(criteria=TenderCriteria(min_submission_days=0), keywords=["подшипников"], platforms=["test"])


@pytest.mark.parametrize(
    "analyzer, notifier, expected_stat",
    [
        (_FakeAnalyzer(error=RuntimeError("ollama unavailable")), _FakeNotifier(True), "ai_failed"),
        (_FakeAnalyzer(score=10), _FakeNotifier(True), "analyzed"),
        (_FakeAnalyzer(score=90), _FakeNotifier(False), "analyzed"),
    ],
    ids=["ai_failure", "low_score", "send_failure"],
)
def test_run_cycle_releases_notification_claim_on_non_delivery_paths(
    tmp_path, monkeypatch, analyzer, notifier, expected_stat
):
    runner, collector, tender, db = _make_orchestrator(tmp_path, analyzer, notifier)

    stats = _run(monkeypatch, runner, collector)

    assert stats[expected_stat] == 1
    assert _claim_count(db) == 0

    # The event was not delivered, so another worker must be able to reserve it
    # immediately rather than waiting for the ten-minute stale-claim TTL.
    fresh_state = NotificationDeliveryState(db)
    assert fresh_state.was_notified(tender, recipient_key=NotificationDeliveryState.DEFAULT_RECIPIENT_KEY) is False


def test_run_cycle_marks_delivery_and_leaves_no_claim(tmp_path, monkeypatch):
    analyzer = _FakeAnalyzer(score=90)
    notifier = _FakeNotifier(True)
    runner, collector, tender, db = _make_orchestrator(tmp_path, analyzer, notifier)

    stats = _run(monkeypatch, runner, collector)

    assert stats["notified"] == 1
    assert notifier.calls == 1
    assert _claim_count(db) == 0
    assert runner.notification_state.was_notified(tender) is True
