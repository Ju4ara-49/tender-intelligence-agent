from __future__ import annotations

import unittest

from src.collectors.b2b_center_reliable import ReliableB2BCenterCollector


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeCollector(ReliableB2BCenterCollector):
    def __init__(self, pages: list[str]) -> None:
        super().__init__({"max_pages": 5, "page_size": 2, "request_delay_seconds": 0})
        self.pages = pages
        self.calls: list[dict] = []

    def _get(self, url: str, params: dict | None = None):
        self.calls.append({"url": url, "params": params or {}})
        offset = int((params or {}).get("from", 0))
        index = offset // 2
        if index >= len(self.pages):
            return _Response("")
        return _Response(self.pages[index])


HTML_PAGE_1 = """
<html><body>
<a class='search-results-title' href='/market/postavka-stankov/tender-1000001/'>Поставка станков для производства</a>
<a class='search-results-title' href='/market/filtry/tender-1000002/'>Фильтры для компрессора</a>
</body></html>
"""
HTML_PAGE_2 = """
<html><body>
<a class='search-results-title' href='/market/remont-stankov/tender-1000003/'>Ремонт токарного станка</a>
<a class='search-results-title' href='/market/podshipniki/tender-1000004/'>Поставка подшипников</a>
</body></html>
"""


class ReliableB2BAdapterTests(unittest.TestCase):
    def test_relevance_gate_removes_unrelated_results(self) -> None:
        collector = _FakeCollector([HTML_PAGE_1])
        results = collector._parse_search_html(HTML_PAGE_1, "станок")
        self.assertEqual([item.external_id for item in results], ["1000001"])

    def test_discovery_uses_offset_pagination(self) -> None:
        collector = _FakeCollector([HTML_PAGE_1, HTML_PAGE_2])
        html = collector._load_search_page("станок")
        self.assertEqual(len(collector.calls), 3)
        self.assertEqual([c["params"]["from"] for c in collector.calls], ["0", "2", "4"])
        self.assertIn("1000003", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
