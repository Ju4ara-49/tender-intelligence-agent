"""Regression tests for the B2B quality-gate flow and the EIS contracts.

Two defects are locked here:

1. ``B2BCenterCollector.get_details`` used to report a failed detail load only
   through ``raw_data["details_loaded"] = False``. Both
   ``src.collectors.detail_contract.enforce_detail_contract`` and
   ``Orchestrator._merge_detail`` recompute that flag from ``detail_status``,
   so the defaulted "success"/"partial" status silently upgraded a detail page
   that had never been parsed into a loaded one. A B2B discovery row that
   already carries customer/price/deadline then passed
   ``KeywordFilter.matches_strict`` without any detail page being loaded.
2. ``EisZakupkiCollector`` defined ``_extract_customer_from_soup`` twice in the
   same class body. The first definition was dead code and lacked the
   commercial organization prefixes, so any future "cleanup" that kept the
   wrong copy would silently drop commercial customers such as ООО/АО.
"""
from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from src.collectors.base import CollectorUnavailableError
from src.collectors.b2b_center_reliable import ReliableB2BCenterCollector
from src.collectors.detail_contract import enforce_detail_contract
from src.collectors.eis_reliable import ReliableEisZakupkiCollector
from src.collectors.eis_zakupki import EisZakupkiCollector
from src.filters.keyword_filter import KeywordFilter
from src.models.tender import Tender
from src.orchestrator import Orchestrator


DETAIL_URL = "https://www.b2b-center.ru/market/tyneli/tender-1000001/"


def _b2b_discovery_tender() -> Tender:
    """Discovery row as produced by the modern B2B search parser."""
    return Tender(
        platform="b2b_center",
        external_id="1000001",
        title="Поставка станков токарных",
        url=DETAIL_URL,
        description="Поставка станков токарных",
        price=500000.0,
        customer="ООО Заказчик",
        deadline=datetime.now(timezone.utc) + timedelta(days=10),
        raw_data={"keyword": "станок", "search_text": "Поставка станков токарных"},
    )


def _b2b_collector() -> ReliableB2BCenterCollector:
    collector = ReliableB2BCenterCollector({"request_delay_seconds": 0})
    enforce_detail_contract(collector)
    collector._tender_urls["1000001"] = DETAIL_URL
    collector._tender_titles["1000001"] = "Поставка станков токарных"
    return collector


class B2BDetailFailureCannotPassQualityGateTests(unittest.TestCase):
    def test_unloaded_detail_page_is_reported_as_failed(self) -> None:
        collector = _b2b_collector()

        with patch.object(collector, "_get", side_effect=RuntimeError("detail page unavailable")):
            detailed = collector.get_details("1000001")

        self.assertIsNotNone(detailed)
        self.assertEqual(detailed.detail_status, "failed")
        self.assertFalse(detailed.raw_data["details_loaded"])
        self.assertIn("detail page unavailable", detailed.detail_diagnostics)

    def test_merged_tender_still_reports_details_as_not_loaded(self) -> None:
        """The detail contract wrapper and the orchestrator merge must not
        recompute ``details_loaded`` back to True for a failed detail load."""
        collector = _b2b_collector()

        with patch.object(collector, "_get", side_effect=RuntimeError("detail page unavailable")):
            detailed = collector.get_details("1000001")

        merged = Orchestrator.__new__(Orchestrator)._merge_detail(_b2b_discovery_tender(), detailed)

        self.assertEqual(merged.detail_status, "failed")
        self.assertFalse(merged.raw_data["details_loaded"])

    def test_quality_gate_rejects_tender_without_loaded_details(self) -> None:
        collector = _b2b_collector()

        with patch.object(collector, "_get", side_effect=RuntimeError("detail page unavailable")):
            detailed = collector.get_details("1000001")

        merged = Orchestrator.__new__(Orchestrator)._merge_detail(_b2b_discovery_tender(), detailed)
        strict = KeywordFilter(include=["станок"], exclude=[])

        self.assertFalse(strict.matches_strict(merged))

    def test_loaded_detail_page_still_passes_the_quality_gate(self) -> None:
        """Guard against "fixing" the gate by rejecting every B2B tender."""
        collector = _b2b_collector()
        detail_html = """
        <html><body>
          <h1 class="trade-header-title">Поставка станков токарных</h1>
          <a data-xid="organizer-information-firm-link">ООО Заказчик</a>
          <span data-xid="total-positions-price-text">1 250 000,00 руб.</span>
          <div>Опубликована 20.09.2026</div>
          <div class="row"><div><span>Окончание приёма заявок</span></div><div>20.10.2026</div></div>
        </body></html>
        """

        with patch.object(
            collector,
            "_get",
            return_value=Mock(status_code=200, text=detail_html),
        ):
            detailed = collector.get_details("1000001")

        self.assertIsNotNone(detailed)
        self.assertEqual(detailed.customer, "ООО Заказчик")
        self.assertIsNotNone(detailed.price)
        self.assertIsNotNone(detailed.deadline)
        self.assertNotEqual(detailed.detail_status, "failed")

        merged = Orchestrator.__new__(Orchestrator)._merge_detail(_b2b_discovery_tender(), detailed)
        strict = KeywordFilter(include=["станок"], exclude=[])

        self.assertTrue(merged.raw_data["details_loaded"])
        self.assertTrue(strict.matches_strict(merged))


class EisCustomerExtractionContractTests(unittest.TestCase):
    DETAIL_HTML = """
    <html><body>
      <td class="tableBlock__col_header">ЗНАЧЕНИЕ ХАРАКТЕРИСТИКИ</td>
      <td class="tableBlock__col_header">ООО "Ромашка"</td>
    </body></html>
    """

    def test_commercial_customer_is_extracted(self) -> None:
        soup = BeautifulSoup(self.DETAIL_HTML, "html.parser")

        self.assertEqual(
            EisZakupkiCollector._extract_customer_from_soup(soup),
            'ООО "Ромашка"',
        )

    def test_service_table_headers_are_not_treated_as_customers(self) -> None:
        soup = BeautifulSoup(
            '<html><body><td class="tableBlock__col_header">ЗНАЧЕНИЕ ХАРАКТЕРИСТИКИ</td>'
            "</body></html>",
            "html.parser",
        )

        self.assertEqual(EisZakupkiCollector._extract_customer_from_soup(soup), "")

    def test_customer_extractor_is_defined_exactly_once(self) -> None:
        """Two same-named methods in one class body mean the first one is dead
        code; only the last definition is reachable."""
        definitions = [
            line
            for line in inspect.getsource(EisZakupkiCollector).splitlines()
            if line.strip().startswith("def _extract_customer_from_soup(")
        ]

        self.assertEqual(len(definitions), 1)


class EisDegradedStateVisibilityTests(unittest.TestCase):
    def _rss_item(self, reg_number: str, title: str) -> str:
        return (
            "<item>"
            f"<title>{title} №{reg_number}</title>"
            f"<link>/epz/order/notice/rgk/view/common-info.html?regNumber={reg_number}</link>"
            f"<guid>{reg_number}</guid>"
            "<description>Тестовое описание</description>"
            "<pubDate>Wed, 16 Sep 2026 10:00:00 +0300</pubDate>"
            "</item>"
        )

    def _rss_xml(self, *items: str) -> str:
        return "<?xml version='1.0'?><rss><channel>" + "".join(items) + "</channel></rss>"

    def test_partial_keyword_failure_is_reported_and_results_are_kept(self) -> None:
        collector = ReliableEisZakupkiCollector({})
        collector._last_search_error = ""

        def fake_get(url, params=None):
            if params and params.get("searchString") == "подшипники":
                raise TimeoutError("connect timeout")
            return Mock(text=self._rss_xml(self._rss_item("0123456789012345", "Поставка станка")))

        with patch.object(collector, "_get", side_effect=fake_get):
            results = collector.search(["станок", "подшипники"])

        self.assertEqual([tender.external_id for tender in results], ["0123456789012345"])
        self.assertIn("incomplete", collector._last_search_error)
        self.assertIn("TimeoutError", collector._last_search_error)

    def test_healthy_keyword_search_reports_no_degraded_state(self) -> None:
        collector = ReliableEisZakupkiCollector({})
        collector._last_search_error = ""

        with patch.object(
            collector,
            "_get",
            return_value=Mock(text=self._rss_xml(self._rss_item("0123456789012345", "Поставка станка"))),
        ):
            results = collector.search(["станок"])

        self.assertEqual(len(results), 1)
        self.assertEqual(collector._last_search_error, "")

    def test_public_fallback_after_healthy_primary_is_marked_degraded(self) -> None:
        collector = ReliableEisZakupkiCollector({"allow_public_fallback": True})
        collector._last_search_error = ""
        fallback_tender = Tender(
            platform="eis",
            external_id="900001",
            title="Поставка подшипников",
            url="https://www.tenderguru.ru/tender/900001",
            description="Поставка подшипников 44-ФЗ",
        )

        with patch.object(collector, "_get", return_value=Mock(text=self._rss_xml())):
            with patch(
                "src.collectors.eis_reliable.tenderguru_search",
                return_value=[fallback_tender],
            ):
                results = collector.search(["подшипники"])

        self.assertEqual([tender.external_id for tender in results], ["900001"])
        self.assertTrue(results[0].raw_data["degraded"])
        self.assertIn("degraded public fallback", collector._last_search_error)

    def test_unreachable_eis_still_fails_closed_by_default(self) -> None:
        collector = ReliableEisZakupkiCollector({})

        with patch.object(collector, "_get", side_effect=TimeoutError("connect timeout")):
            with self.assertRaises(CollectorUnavailableError) as ctx:
                collector.search(["подшипники"])

        self.assertIn("eis: search endpoint unavailable", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)