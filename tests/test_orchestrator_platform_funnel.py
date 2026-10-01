"""Воронка по площадкам: видно, на каком шаге пайплайна пропадают тендеры."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import src.orchestrator as orch_module
from src.models.tender import Tender
from src.orchestrator import Orchestrator
from src.telegram_settings import TenderCriteria


class _FakeCollector:
    def __init__(self, platform: str, tenders: list[Tender]) -> None:
        self.platform = platform
        self.config = {"lookback_days": 3650}
        self._tenders = tenders

    def search(self, keywords, since=None):
        return list(self._tenders)

    def get_details(self, external_id):
        return None  # деталей нет -> failed


def _orchestrator(collectors):
    o = Orchestrator.__new__(Orchestrator)
    o.settings = SimpleNamespace(
        config={"search": {}, "collectors": {}, "export": {"output_dir": "output"}},
        include_keywords=["станок"],
    )
    o.db = MagicMock()
    o.db.next_search_number.return_value = 1
    o.criteria_store = MagicMock()
    o.criteria_store.get_enabled_platforms.return_value = None
    o.notification_state = MagicMock()
    o.analyzer = MagicMock()
    o.notifier = MagicMock()
    o.email_notifier = MagicMock()
    o._stop_requested = False
    o.last_run_results = []
    o.last_platform_errors = {}
    o.last_platform_funnel = {}
    return o


def test_funnel_counts_every_platform_including_empty(monkeypatch):
    b2b = _FakeCollector(
        "b2b_center",
        [Tender(platform="b2b_center", external_id=str(i), title="Станок", url=f"https://x/{i}") for i in range(3)],
    )
    empty = _FakeCollector("rts_tender", [])
    monkeypatch.setattr(orch_module, "get_enabled_collectors", lambda *a, **k: [b2b, empty])
    monkeypatch.setattr(orch_module, "export_tenders_to_excel", lambda *a, **k: "x.xlsx")

    o = _orchestrator([b2b, empty])
    o.run_cycle(criteria=TenderCriteria(), keywords=["станок"], platforms=["b2b_center", "rts_tender"])

    funnel = o.last_platform_funnel
    assert funnel["b2b_center"]["raw"] == 3
    assert funnel["b2b_center"]["unique"] == 3
    # площадка с нулём результатов обязана быть видна в воронке
    assert funnel["rts_tender"]["raw"] == 0
    # сумма исходов мягкого фильтра равна числу уникальных
    b = funnel["b2b_center"]
    assert b.get("soft_ok", 0) + b.get("soft_rejected", 0) + b.get("too_old", 0) == 3


def test_funnel_resets_between_runs(monkeypatch):
    c = _FakeCollector("eis", [])
    monkeypatch.setattr(orch_module, "get_enabled_collectors", lambda *a, **k: [c])
    monkeypatch.setattr(orch_module, "export_tenders_to_excel", lambda *a, **k: "x.xlsx")
    o = _orchestrator([c])
    o.last_platform_funnel = {"stale": {"raw": 99}}
    o.run_cycle(criteria=TenderCriteria(), keywords=["x"], platforms=["eis"])
    assert "stale" not in o.last_platform_funnel
