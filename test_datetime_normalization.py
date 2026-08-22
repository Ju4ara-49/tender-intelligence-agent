import unittest
from datetime import datetime, timezone

from src.orchestrator import Orchestrator


class TestDatetimeNormalization(unittest.TestCase):
    def test_naive_portal_datetime_is_treated_as_moscow_and_converted_to_utc(self):
        value = datetime(2025, 12, 4, 0, 0, 0)
        normalized = Orchestrator._normalize_datetime(value)

        self.assertIsNotNone(normalized)
        self.assertEqual(normalized.tzinfo, timezone.utc)
        self.assertEqual(normalized, datetime(2025, 12, 3, 21, 0, tzinfo=timezone.utc))

    def test_aware_datetime_is_not_shifted(self):
        value = datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)
        normalized = Orchestrator._normalize_datetime(value)

        self.assertEqual(normalized, value)

    def test_none_stays_none(self):
        self.assertIsNone(Orchestrator._normalize_datetime(None))


if __name__ == "__main__":
    unittest.main()
