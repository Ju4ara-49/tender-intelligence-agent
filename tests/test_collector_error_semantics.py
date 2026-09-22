"""Error-semantics и multi-keyword state regression tests для collectors.

Контракт (collector failure contract):
- HTTP 403/5xx, timeout, CAPTCHA/WAF → CollectorUnavailableError, НИКОГДА не
  молчаливый [] (пустой результат = SUCCESS EMPTY, недоступность = UNAVAILABLE);
- search(A) → search(B) → search(A): результаты изолированы, без утечки
  состояния между вызовами; повторный запуск работает.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from src.collectors.base import CollectorUnavailableError
from src.collectors.browser_public_reliable import (
    ReliableRtsTenderCollector,
    ReliableTmkCollector,
)
from src.collectors.eis_zakupki import SEARCH_URL, EisZakupkiCollector
from src.collectors.fabrikant_v2 import FabrikantV2Collector
from src.collectors.rosatom import RosatomCollector
from src.models.tender import Tender


# ----------------------------------------------------------------------------
# EIS: error semantics
# ----------------------------------------------------------------------------


def _collector_with_get(monkeypatch, handler) -> EisZakupkiCollector:
    collector = EisZakupkiCollector({"timeout_seconds": 1})
    monkeypatch.setattr(collector, "_get", handler)
    return collector


def _eis_empty_handler():
    def handler(url, params=None):
        import requests as _requests
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "<html><body>Нет найденных закупок</body></html>"
        return resp
    return handler


def test_eis_search_http_403_is_unavailable_not_empty(monkeypatch):
    def handler(url, params=None):
        resp = MagicMock()
        resp.status_code = 403
        resp.text = "Forbidden"
        raise requests.HTTPError("403 Forbidden", response=resp)

    collector = _collector_with_get(monkeypatch, handler)
    with pytest.raises(CollectorUnavailableError, match="unavailable"):
        collector.search(["подшипники"])


def test_eis_search_timeout_is_unavailable_not_empty(monkeypatch):
    def handler(url, params=None):
        raise requests.Timeout("connect timeout")

    collector = _collector_with_get(monkeypatch, handler)
    with pytest.raises(CollectorUnavailableError, match="Timeout"):
        collector.search(["подшипники"])


def test_eis_search_http_500_after_retries_is_unavailable_not_empty(monkeypatch):
    def handler(url, params=None):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"
        raise requests.HTTPError("500 Server Error", response=resp)

    collector = _collector_with_get(monkeypatch, handler)
    with pytest.raises(CollectorUnavailableError, match="unavailable"):
        collector.search(["подшипники"])


def test_eis_search_captcha_page_is_unavailable_not_empty(monkeypatch):
    captcha_html = (
        "<html><head><title>Проверка браузера перед доступом к сайту</title></head>"
        "<body><div class='g-recaptcha'></div></body></html>"
    )

    def handler(url, params=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = captcha_html
        return resp

    collector = _collector_with_get(monkeypatch, handler)
    with pytest.raises(CollectorUnavailableError, match="captcha"):
        collector.search(["подшипники"])


def test_eis_search_genuinely_empty_response_is_empty(monkeypatch):
    """Реальный пустой ответ ЕИС (нет карточек) — честный EMPTY, не ошибка."""
    html = "<html><body><p>Нет найденных закупок</p></body></html>"

    def handler(url, params=None):
        assert url == SEARCH_URL
        resp = MagicMock()
        resp.status_code = 200
        resp.text = html
        return resp

    collector = _collector_with_get(monkeypatch, handler)
    assert collector.search(["подшипники"]) == []


def test_eis_search_partial_failure_returns_partial_results(monkeypatch):
    """Один keyword упал, второй нашёл — возвращаем частичный результат,
    а не UNAVAILABLE и не []: SUCCESS PARTIAL."""
    found = [
        Tender(platform="eis", external_id="1001", title="Поставка подшипников", url="https://zakupki.gov.ru/1")
    ]

    def failing_search_keyword(keyword, since):
        if keyword == "муфты":
            raise requests.ConnectionError("connection reset")
        return found

    collector = EisZakupkiCollector({"request_delay_seconds": 0})
    monkeypatch.setattr(collector, "_search_keyword", failing_search_keyword)

    results = collector.search(["муфты", "подшипники"], since=None)
    assert [t.external_id for t in results] == ["1001"]


def test_eis_search_all_keywords_failed_raises_unavailable(monkeypatch):
    def failing_search_keyword(keyword, since):
        raise requests.ConnectionError("connection reset")

    collector = EisZakupkiCollector({"request_delay_seconds": 0})
    monkeypatch.setattr(collector, "_search_keyword", failing_search_keyword)

    with pytest.raises(CollectorUnavailableError, match="all 2 keyword"):
        collector.search(["муфты", "подшипники"])


# ----------------------------------------------------------------------------
# Rosatom: WAF / challenge page → CollectorUnavailableError, not []
# ----------------------------------------------------------------------------

def test_rosatom_parse_results_waf_raises_unavailable_not_empty():
    """Regression: RosatomCollector._parse_results returned [] on a WAF/challenge
    page. This silently looked like a healthy empty search (SUCCESS EMPTY)
    instead of UNAVAILABLE. It must raise CollectorUnavailableError."""
    waf_html = "<html><body>Web Application Firewall — временно заблокирован</body></html>"
    with pytest.raises(CollectorUnavailableError, match="WAF"):
        RosatomCollector({})._parse_results(waf_html)


def test_rosatom_parse_results_genuinely_empty_is_empty():
    """A page with no procurements, no WAF → empty list (SUCCESS EMPTY)."""
    html = "<html><body><p>Нет закупок</p></body></html>"
    assert RosatomCollector({})._parse_results(html) == []


# ----------------------------------------------------------------------------
# ReliableBrowserSearchMixin: WAF / challenge / empty page → UNAVAILABLE, not []
# ----------------------------------------------------------------------------

def test_browser_search_one_waf_raises_unavailable(monkeypatch):
    """The reliable mixin overrides _search_one and previously lacked the WAF
    check that the base _BrowserTenderCollector._search_one had. A challenge
    page with no parsed results was treated as RESULT_PARSER_ZERO (a parser
    issue), not as UNAVAILABLE. It must raise CollectorUnavailableError."""
    collector = ReliableRtsTenderCollector({})
    waf_html = "<html><body>Web Application Firewall</body></html>"

    monkeypatch.setattr(collector, "timeout_ms", 5000)
    monkeypatch.setattr(collector, "max_results", 100)
    monkeypatch.setattr(collector, "BASE_URL", "https://223.rts-tender.ru/")
    monkeypatch.setattr(collector, "_goto", lambda *a, **kw: None)
    monkeypatch.setattr(collector, "_perform_search", lambda *a, **kw: True)
    monkeypatch.setattr(collector, "_dismiss_consent", lambda *a, **kw: None)
    monkeypatch.setattr(collector, "_expand_results", lambda *a, **kw: None)
    monkeypatch.setattr(collector, "_collect_rendered_html", lambda *a, **kw: waf_html)

    fake_browser = MagicMock()
    fake_context = MagicMock()
    fake_page = MagicMock()
    fake_pw = MagicMock()
    fake_pw.chromium.launch.return_value = fake_browser
    fake_browser.new_context.return_value = fake_context
    fake_context.new_page.return_value = fake_page
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: fake_pw)

    with pytest.raises(CollectorUnavailableError, match="access/challenge page"):
        collector._search_one("станок")


def test_browser_search_one_empty_html_raises_unavailable(monkeypatch):
    """An empty HTML response from the portal (not just zero results) is
    UNAVAILABLE, not SUCCESS EMPTY."""
    collector = ReliableTmkCollector({})

    monkeypatch.setattr(collector, "timeout_ms", 5000)
    monkeypatch.setattr(collector, "max_results", 100)
    monkeypatch.setattr(collector, "BASE_URL", "https://stock.tmk-group.com/auction/")
    monkeypatch.setattr(collector, "_goto", lambda *a, **kw: None)
    monkeypatch.setattr(collector, "_perform_search", lambda *a, **kw: True)
    monkeypatch.setattr(collector, "_dismiss_consent", lambda *a, **kw: None)
    monkeypatch.setattr(collector, "_expand_results", lambda *a, **kw: None)
    monkeypatch.setattr(collector, "_collect_rendered_html", lambda *a, **kw: "")

    fake_pw = MagicMock()
    with pytest.raises(CollectorUnavailableError, match="empty page"):
        collector._search_one("станок")


# ----------------------------------------------------------------------------
# Multi-keyword state isolation
# ----------------------------------------------------------------------------

def test_eis_multi_keyword_no_state_leakage(monkeypatch):
    """search(A) → search(B): results from B must not contain state from A."""
    collector = _collector_with_get(monkeypatch, _eis_empty_handler())
    a = collector.search(["станок"])
    b = collector.search(["подшипник"])
    assert a == [] and b == []

    # Search A again — must still work, no residual state
    a2 = collector.search(["станок"])
    assert a2 == []


def test_fabrikant_multi_keyword_no_state_leakage(monkeypatch):
    """Each keyword search is independent; _urls accumulates across keywords
    within a single search() call (for detail enrichment), but a second
    search() call must not see stale state from the first keyword."""
    collector = FabrikantV2Collector({})

    def fake_search_one(query):
        if "станок" in query:
            collector._urls["STANOK"] = "https://soap2.fabrikant.ru/223/procedure/STANOK"
            return [Tender(
                platform="fabrikant",
                external_id="STANOK",
                title="Закупка станка",
                url="https://soap2.fabrikant.ru/223/procedure/STANOK",
            )]
        if "подшипник" in query:
            collector._urls["SUB"] = "https://soap2.fabrikant.ru/223/procedure/SUB"
            return [Tender(
                platform="fabrikant",
                external_id="SUB",
                title="Закупка подшипников",
                url="https://soap2.fabrikant.ru/223/procedure/SUB",
            )]
        return []

    monkeypatch.setattr(collector, "_search_one", fake_search_one)
    monkeypatch.setattr(collector, "timeout_ms", 5000)
    monkeypatch.setattr(collector, "max_results", 100)

    # First search: keyword A
    results_a = collector.search(["станок"])
    assert len(results_a) == 1
    assert results_a[0].external_id == "STANOK"

    # Second search: keyword B — must NOT return A's results
    results_b = collector.search(["подшипник"])
    assert len(results_b) == 1
    assert results_b[0].external_id == "SUB"

    # Search A again — must still return A's results, not B's
    results_a2 = collector.search(["станок"])
    assert len(results_a2) == 1
    assert results_a2[0].external_id == "STANOK"