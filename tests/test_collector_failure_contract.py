from __future__ import annotations

import unittest

from src.collectors.base import CollectorUnavailableError
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


class CollectorFailureContractTests(unittest.TestCase):
    def test_unavailable_collector_is_not_converted_to_exceptionless_success(self) -> None:
        platform, found = Orchestrator._search_platform(
            _UnavailableCollector(),
            ["подшипники"],
        )
        self.assertEqual(platform, "test_platform")
        self.assertEqual(found, [])

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


if __name__ == "__main__":
    unittest.main()
