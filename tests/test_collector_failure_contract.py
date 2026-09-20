from __future__ import annotations

import unittest
from unittest.mock import patch

from src.collectors.base import CollectorUnavailableError
from src.collectors.eis_reliable import ReliableEisZakupkiCollector
from src.models.tender import Tender
from src.orchestrator import Orchestrator


class _UnavailableCollector:
    platform = "test_platform"
    config = {"lookback_days": 3}

    def search(self, keywords, since=None):
        raise CollectorUnavailableError("test platform timeout")


class _BrokenCollector:
    platform = "broken_platform"
    config = {"lookback_days": 3}

    def search(self, keywords, since=None):
        raise RuntimeError("unexpected parser failure")


class _UnavailableEisCollector(ReliableEisZakupkiCollector):
    def _get(self, url, params=None):
        raise TimeoutError("connect timeout")


class CollectorFailureContractTests(unittest.TestCase):
    def test_unavailable_collector_is_not_converted_to_exceptionless_success(self) -> None:
        collector = _UnavailableCollector()
        platform, found = Orchestrator._search_platform(collector, ["подшипники"])
        self.assertEqual(platform, "test_platform")
        self.assertEqual(found, [])
        self.assertEqual(collector._last_search_error, "test platform timeout")

    def test_generic_collector_error_is_recorded_on_collector(self) -> None:
        collector = _BrokenCollector()
        platform, found = Orchestrator._search_platform(collector, ["подшипники"])
        self.assertEqual(platform, "broken_platform")
        self.assertEqual(found, [])
        self.assertIn("RuntimeError", getattr(collector, "_last_search_error", ""))

    def test_unavailable_error_has_dedicated_type(self) -> None:
        error = CollectorUnavailableError("timeout")
        self.assertIsInstance(error, Exception)
        self.assertNotIsInstance(error, KeyboardInterrupt)
        self.assertEqual(str(error), "timeout")

    def test_eis_reliable_adapter_fails_closed_on_transport_error(self) -> None:
        collector = _UnavailableEisCollector({"timeout_seconds": 1})
        with self.assertRaises(CollectorUnavailableError) as ctx:
            collector.search(["подшипники"])
        self.assertIn("eis: search endpoint unavailable", str(ctx.exception))


class _DegradedFallbackTender:
    """Helper producing one degraded public-index result."""

    @staticmethod
    def build() -> Tender:
        return Tender(
            platform="eis",
            external_id="900001",
            title="Поставка подшипников",
            url="https://www.tenderguru.ru/tender/900001",
            description="Поставка подшипников 44-ФЗ",
        )


class EisDegradedFallbackTests(unittest.TestCase):
    """The public-index fallback is a degraded mode and must stay opt-in."""

    def test_default_configuration_fails_closed_even_when_fallback_is_reachable(self) -> None:
        collector = _UnavailableEisCollector({"timeout_seconds": 1})
        with patch(
            "src.collectors.eis_reliable.tenderguru_search",
            return_value=[_DegradedFallbackTender.build()],
        ):
            with self.assertRaises(CollectorUnavailableError) as ctx:
                collector.search(["подшипники"])
        self.assertIn("eis: search endpoint unavailable", str(ctx.exception))

    def test_opt_in_fallback_marks_results_degraded_and_reports_the_error(self) -> None:
        collector = _UnavailableEisCollector({"timeout_seconds": 1, "allow_public_fallback": True})
        with patch(
            "src.collectors.eis_reliable.tenderguru_search",
            return_value=[_DegradedFallbackTender.build()],
        ):
            results = collector.search(["подшипники"])

        self.assertEqual([tender.external_id for tender in results], ["900001"])
        self.assertTrue(results[0].raw_data["degraded"])
        self.assertEqual(results[0].raw_data["degraded_source"], "tenderguru_public_fallback")
        self.assertIn("degraded public fallback", collector._last_search_error)
        self.assertIn("TimeoutError", collector._last_search_error)

    def test_opt_in_fallback_without_results_still_fails_closed(self) -> None:
        collector = _UnavailableEisCollector({"timeout_seconds": 1, "allow_public_fallback": True})
        with patch("src.collectors.eis_reliable.tenderguru_search", return_value=[]):
            with self.assertRaises(CollectorUnavailableError) as ctx:
                collector.search(["подшипники"])
        self.assertIn("eis: search endpoint unavailable", str(ctx.exception))

    def test_orchestrator_keeps_a_collector_reported_degraded_state(self) -> None:
        class _DegradedCollector:
            platform = "eis"
            config = {"lookback_days": 3}

            def search(self, keywords, since=None):
                self._last_search_error = "eis: degraded public fallback used"
                return []

        collector = _DegradedCollector()
        platform, found = Orchestrator._search_platform(collector, ["подшипники"])

        self.assertEqual(platform, "eis")
        self.assertEqual(found, [])
        self.assertIn("degraded", collector._last_search_error)


if __name__ == "__main__":
    unittest.main()
