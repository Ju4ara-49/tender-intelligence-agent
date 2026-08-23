from __future__ import annotations

from types import SimpleNamespace

from src.collectors.b2b_center_reliable import ReliableB2BCenterCollector


def _page(ids: list[int]) -> str:
    rows = "".join(
        f"<tr><td><a class='search-results-title' href='/market/test-{i}/tender-{i}'>"
        f"<span class='search-results-title-desc'>Станок {i}</span></a></td></tr>"
        for i in ids
    )
    return f"<table class='search-results'><tbody>{rows}</tbody></table>"


def test_b2b_reliable_search_requests_offset_pages(monkeypatch):
    collector = ReliableB2BCenterCollector(
        {"max_pages": 20, "page_size": 20, "max_results": 500, "request_delay_seconds": 0}
    )
    calls: list[int] = []

    pages = {
        0: _page(list(range(1000001, 1000021))),
        20: _page(list(range(1000021, 1000041))),
        40: _page(list(range(1000041, 1000061))),
        60: "",
    }

    def fake_get(url, params=None):
        calls.append(int(params["from"]))
        return SimpleNamespace(text=pages[int(params["from"])])

    monkeypatch.setattr(collector, "_get", fake_get)
    html = collector._load_search_page("Станок")

    assert calls == [0, 20, 40, 60]
    assert html.count("search-results-title") == 60


def test_b2b_configured_one_page_does_not_disable_broad_discovery(monkeypatch):
    collector = ReliableB2BCenterCollector(
        {"max_pages": 1, "page_size": 20, "max_results": 500, "request_delay_seconds": 0}
    )
    calls: list[int] = []

    def fake_get(url, params=None):
        calls.append(int(params["from"]))
        if len(calls) == 1:
            return SimpleNamespace(text=_page(list(range(2000001, 2000021))))
        return SimpleNamespace(text="")

    monkeypatch.setattr(collector, "_get", fake_get)
    collector._load_search_page("станок")

    assert calls[:2] == [0, 20]
