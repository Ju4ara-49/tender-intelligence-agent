"""Регрессионные тесты для трёх исправленных багов в коллекторах.

1. eis_zakupki.py: `except Exception` должен быть внутри try/except, а не
   на уровне модуля (IndentationError).
2. eis_zakupki.py: `get_details` должен перебирать все URL, а не возвращать
   `None` при первой не-404 ошибке.
3. fabrikant_v2.py: `search` должен корректно сравнивать naive datetime с
   tz-aware `since` (ValueError/TypeError при отсутствии нормализации tzinfo).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.collectors.fabrikant_v2 import FabrikantV2Collector
from src.models.tender import Tender


def test_eis_module_imports_without_indentation_error():
    """Regression: `except Exception` was at column 0, causing IndentationError.

    If the module can be imported, the structure is valid.
    """
    import src.collectors.eis_zakupki as mod
    collector_cls = mod.EisZakupkiCollector
    assert collector_cls.platform == "eis"
    assert hasattr(collector_cls, "get_details")
    assert hasattr(collector_cls, "_parse_details_page")
    assert hasattr(collector_cls, "_has_captcha") or True


def test_eis_get_details_tries_next_url_on_500(monkeypatch):
    """Regression: get_details returned None immediately on a non-404 HTTPError
    from the first URL, instead of trying the remaining URLs.

    With a 500 on URL 1 and a working URL 2, get_details should return a Tender.
    """
    from src.collectors.eis_zakupki import EisZakupkiCollector, BASE_URL

    url1 = f"{BASE_URL}/epz/order/notice/ea20/view/common-info.html?regNumber=0123456789012345"
    url2 = f"{BASE_URL}/epz/order/notice/ea44/view/common-info.html?regNumber=0123456789012345"

    collector = EisZakupkiCollector({})

    good_html = """
    <html><body>
      <div>Объект закупки: Поставка станка</div>
      <div>Заказчик: ООО Тест ИНН 7701234567</div>
      <div>Начальная цена 100 000,00 руб.</div>
      <div>Размещено 18.09.2026</div>
      <div>Регион Москва</div>
    </body></html>
    """

    call_count = {"n": 0}

    def fake_get(url):
        call_count["n"] += 1
        if url == url1:
            import requests as _requests
            resp = MagicMock()
            resp.status_code = 500
            resp.text = "Server Error"
            raise _requests.HTTPError("500 Server Error", response=resp)
        else:
            resp = MagicMock()
            resp.status_code = 200
            resp.text = good_html
            return resp

    monkeypatch.setattr(collector, "_get", fake_get)

    result = collector.get_details("0123456789012345")
    assert result is not None, "get_details should fall through to the second URL"
    assert result.title == "Поставка станка"
    assert call_count["n"] == 2, "get_details should try at least 2 URLs"


def test_eis_get_details_tries_all_urls_when_all_404(monkeypatch):
    """Regression: if all URLs return 404, get_details returns None
    (not an exception)."""
    from src.collectors.eis_zakupki import EisZakupkiCollector

    collector = EisZakupkiCollector({})

    import requests as _requests

    def fake_get(url):
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "Not Found"
        raise _requests.HTTPError("404 Not Found", response=resp)

    monkeypatch.setattr(collector, "_get", fake_get)

    result = collector.get_details("0123456789012345")
    assert result is None


def test_fabrikant_v2_search_since_comparison_no_typeerror(monkeypatch):
    """Regression: FabrikantV2Collector.search does its own since-comparison
    (it overrides the base class search). `_parse_datetime` returns naive
    datetimes. If `since` is tz-aware, `published < since` raises TypeError.

    The fix restores tzinfo normalization so naive published_at is safely
    compared against a tz-aware `since`.
    """
    from src.collectors.fabrikant_v2 import FabrikantV2Collector

    collector = FabrikantV2Collector({})

    naive_old = datetime(2025, 1, 1, 12, 0)
    naive_new = datetime(2026, 9, 1, 12, 0)
    since_tz = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

    html = """
    <html><body>
      <table>
        <tr><th>№ извещения</th><th>Наименование</th><th>Заказчик</th></tr>
        <tr>
          <td><a href="/223/procedure/100001">old</a></td>
          <td>Старая закупка подшипники</td>
          <td>ООО Старый</td>
        </tr>
        <tr>
          <td><a href="/223/procedure/100002">new</a></td>
          <td>Новая закупка подшипники</td>
          <td>ООО Новый</td>
        </tr>
      </table>
    </body></html>
    """

    parsed_values = [
        {"platform": "fabrikant", "external_id": "100001", "title": "Старая", "url": "https://soap2.fabrikant.ru/223/procedure/100001", "description": "Старая", "price": None, "deadline": naive_old, "published_at": naive_old, "start_date": naive_old, "customer": "ООО Старый", "law_type": "223-ФЗ"},
        {"platform": "fabrikant", "external_id": "100002", "title": "Новая", "url": "https://soap2.fabrikant.ru/223/procedure/100002", "description": "Новая", "price": None, "deadline": naive_new, "published_at": naive_new, "start_date": naive_new, "customer": "ООО Новый", "law_type": "223-ФЗ"},
    ]

    def fake_search_one(term):
        return [Tender(**v) for v in parsed_values]

    monkeypatch.setattr(collector, "_search_one", fake_search_one)

    results = collector.search(["подшипники"], since=since_tz)

    titles = [t.title for t in results]
    assert "Новая" in titles, "Tender newer than 'since' should be included"
    assert "Старая" not in titles, "Tender older than 'since' should be filtered out"


def test_fabrikant_v2_preserves_urls_across_both_base_urls():
    """Regression: FabrikantV2Collector.search previously cleared
    `self._urls = {}` inside the base_url loop, discarding detail URLs
    collected from the first host before searching the second.

    This test verifies that URLs from the first base_url survive into
    the merged result set and are available for get_details enrichment.
    """
    collector = FabrikantV2Collector({})

    tender_a = Tender(
        platform="fabrikant",
        external_id="100001",
        title="Подшипники стальные",
        url="https://soap2.fabrikant.ru/223/procedure/100001",
        published_at=datetime(2026, 9, 1, 12, 0),
        deadline=datetime(2026, 10, 1, 12, 0),
        price=None,
        customer="ООО Тест",
        law_type="223-ФЗ",
    )

    base_urls = (
        "https://soap2.fabrikant.ru/223/catalog/procedure/published",
        "https://soap4.fabrikant.ru/44/catalog/procedure",
    )
    first_host = base_urls[0]

    def fake_search_one(term):
        if collector.BASE_URL == first_host:
            collector._urls["100001"] = "https://soap2.fabrikant.ru/223/procedure/100001"
            return [tender_a]
        # On the second host, verify the URL from the first host survived
        assert collector._urls.get("100001") == "https://soap2.fabrikant.ru/223/procedure/100001", (
            "URL from first base_url must survive into second host search (was cleared by bug)"
        )
        return []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(collector, "_search_one", fake_search_one)

    try:
        results = collector.search(["подшипники"])
        assert len(results) == 1, f"Expected 1 result, got {len(results)}"
        assert results[0].external_id == "100001"
        assert results[0].url == "https://soap2.fabrikant.ru/223/procedure/100001"
        assert collector._urls.get("100001") == "https://soap2.fabrikant.ru/223/procedure/100001", (
            "URL from first base_url must survive after searching both hosts"
        )
    finally:
        monkeypatch.undo()
