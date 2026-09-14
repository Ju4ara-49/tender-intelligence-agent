from __future__ import annotations

import unittest

from src.collectors.base import CollectorUnavailableError
from src.collectors.eis_reliable import ReliableEisZakupkiCollector
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


if __name__ == "__main__":
    unittest.main()
