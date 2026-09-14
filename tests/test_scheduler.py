from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import src.scheduler as scheduler_module
from src.settings import AppSettings


class _FakeScheduler:
    instances: list["_FakeScheduler"] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.jobs = []
        self.started = False
        type(self).instances.append(self)

    def add_job(self, job, **kwargs):
        self.jobs.append((job, kwargs))

    def start(self):
        self.started = True


def _settings(run_on_start: bool = False):
    return SimpleNamespace(
        config={"app": {"timezone": "Europe/Moscow"}},
        scheduler_interval_minutes=15,
        run_on_start=run_on_start,
    )


def test_scheduler_registers_monitor_job_and_starts():
    class FakeOrchestrator:
        calls = 0

        def __init__(self, settings):
            self.settings = settings

        def run_cycle(self):
            type(self).calls += 1

    _FakeScheduler.instances.clear()
    with patch.object(scheduler_module, "BlockingScheduler", _FakeScheduler), patch.object(
        scheduler_module, "Orchestrator", FakeOrchestrator
    ):
        scheduler_module.run_scheduled(_settings(run_on_start=False))

    fake = _FakeScheduler.instances[-1]
    assert fake.started is True
    assert len(fake.jobs) == 1
    _, kwargs = fake.jobs[0]
    assert kwargs["id"] == "tender_monitor"
    assert kwargs["name"] == "Tender Intelligence Monitor"
    assert kwargs["replace_existing"] is True
    assert FakeOrchestrator.calls == 0


def test_scheduler_run_on_start_executes_cycle_immediately():
    class FakeOrchestrator:
        calls = 0

        def __init__(self, settings):
            self.settings = settings

        def run_cycle(self):
            type(self).calls += 1

    _FakeScheduler.instances.clear()
    with patch.object(scheduler_module, "BlockingScheduler", _FakeScheduler), patch.object(
        scheduler_module, "Orchestrator", FakeOrchestrator
    ):
        scheduler_module.run_scheduled(_settings(run_on_start=True))

    fake = _FakeScheduler.instances[-1]
    assert fake.started is True
    assert FakeOrchestrator.calls == 1


def test_scheduler_job_contains_monitoring_error_and_does_not_escape():
    class FakeOrchestrator:
        def __init__(self, settings):
            self.settings = settings

        def run_cycle(self):
            raise RuntimeError("collector failure must not kill scheduler")

    _FakeScheduler.instances.clear()
    with patch.object(scheduler_module, "BlockingScheduler", _FakeScheduler), patch.object(
        scheduler_module, "Orchestrator", FakeOrchestrator
    ):
        scheduler_module.run_scheduled(_settings(run_on_start=False))
        fake = _FakeScheduler.instances[-1]
        job = fake.jobs[0][0]
        job()

    assert fake.started is True


def test_scheduler_interval_must_be_positive():
    settings = AppSettings(config={"scheduler": {"interval_minutes": 0}}, keywords={})
    with pytest.raises(ValueError, match="больше нуля"):
        _ = settings.scheduler_interval_minutes


def test_scheduler_interval_defaults_to_one_hour():
    settings = AppSettings(config={}, keywords={})
    assert settings.scheduler_interval_minutes == 60
