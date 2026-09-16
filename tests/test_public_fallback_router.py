from __future__ import annotations

import unittest
from unittest.mock import patch

from src.collectors.base import BaseCollector, CollectorUnavailableError
from src.collectors.public_fallback_router import PublicFallbackRouter
from src.models.tender import Tender


class _UnavailableCollector:
    platform = "tmk"

    def __init__(self) -> None:
        self.details_calls = 0

    def search(self, keywords, since=None):
        raise CollectorUnavailableError("portal blocked")

    def get_details(self, external_id):
        self.details_calls += 1
        return None


class _WorkingCollector:
    platform = "tmk"

    def search(self, keywords, since=None):
        return [Tender(platform="tmk", external_id="1", title="Подшипники", url="https://example/1")]

    def get_details(self, external_id):
        return external_id


class _EmptyCollector(_WorkingCollector):
    def search(self, keywords, since=None):
        return []


class PublicFallbackRouterTests(unittest.TestCase):
    def test_router_satisfies_base_collector_contract(self):
        router = PublicFallbackRouter(_WorkingCollector(), {"public_fallback": True})
        self.assertIsInstance(router, BaseCollector)
        self.assertEqual(router.platform, "tmk")

    def test_primary_collector_is_used_first(self):
        collector = _WorkingCollector()
        router = PublicFallbackRouter(collector, {"public_fallback": True})
        with patch("src.collectors.public_fallback_router.tenderguru_search") as fallback:
            result = router.search(["подшипники"])
        self.assertEqual(len(result), 1)
        fallback.assert_not_called()

    def test_unavailable_primary_uses_public_fallback_and_preserves_platform(self):
        collector = _UnavailableCollector()
        router = PublicFallbackRouter(collector, {"public_fallback": True, "max_results": 10})
        fallback_result = Tender(platform="tmk", external_id="42", title="Поставка подшипников", url="https://www.tenderguru.ru/tender/42", raw_data={})
        with patch("src.collectors.public_fallback_router.tenderguru_search", return_value=[fallback_result]):
            result = router.search(["подшипников"])
        self.assertEqual([item.external_id for item in result], ["42"])
        self.assertEqual(result[0].platform, "tmk")
        self.assertEqual(result[0].raw_data["adapter_mode"], "tenderguru_public_fallback")
        self.assertEqual(result[0].raw_data["requested_keyword"], "подшипников")
        self.assertFalse(result[0].raw_data["details_loaded"])
        self.assertIs(router.get_details("42"), result[0])

    def test_empty_primary_can_use_public_fallback(self):
        collector = _EmptyCollector()
        router = PublicFallbackRouter(collector, {"public_fallback": True})
        fallback_result = Tender(platform="tmk", external_id="43", title="Станки", url="https://example/43", raw_data={})
        with patch("src.collectors.public_fallback_router.tenderguru_search", return_value=[fallback_result]):
            result = router.search(["станок"])
        self.assertEqual([item.external_id for item in result], ["43"])
        self.assertEqual(result[0].raw_data["adapter_mode"], "tenderguru_public_fallback")

    def test_fallback_can_be_disabled(self):
        collector = _UnavailableCollector()
        router = PublicFallbackRouter(collector, {"public_fallback": False})
        with self.assertRaises(CollectorUnavailableError):
            router.search(["станок"])

    def test_details_are_delegated_to_primary_collector(self):
        collector = _WorkingCollector()
        router = PublicFallbackRouter(collector, {"public_fallback": True})
        self.assertEqual(router.get_details("123"), "123")


if __name__ == "__main__":
    unittest.main()
