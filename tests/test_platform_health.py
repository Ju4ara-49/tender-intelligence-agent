from src.collectors.health import check_platforms


class _FakeCollector:
    def __init__(self, platform, result=None, error=None):
        self.platform = platform
        self.result = result
        self.error = error

    def search(self, keywords, since=None):
        if self.error:
            raise self.error
        return self.result


def test_health_marks_parsed_search_as_ok(monkeypatch):
    monkeypatch.setattr(
        "src.collectors.health.get_enabled_collectors",
        lambda config, enabled_platforms=None: [_FakeCollector("b2b_center", [object()])],
    )
    report = check_platforms({}, query="подшипники")
    assert report[0].status == "ok"
    assert report[0].results == 1


def test_health_does_not_hide_zero_result_regression(monkeypatch):
    monkeypatch.setattr(
        "src.collectors.health.get_enabled_collectors",
        lambda config, enabled_platforms=None: [_FakeCollector("rts_tender", [])],
    )
    report = check_platforms({}, query="подшипники")
    assert report[0].status == "zero_results"
    assert report[0].results == 0


def test_health_reports_collector_exception(monkeypatch):
    monkeypatch.setattr(
        "src.collectors.health.get_enabled_collectors",
        lambda config, enabled_platforms=None: [_FakeCollector("tmk", error=TimeoutError("network timeout"))],
    )
    report = check_platforms({}, query="подшипники")
    assert report[0].status == "error"
    assert "TimeoutError" in report[0].error
