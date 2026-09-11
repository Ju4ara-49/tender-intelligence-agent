from __future__ import annotations

import unittest

from src.monitoring.change_policy import classify_changed_fields, significant_diff
from src.monitoring.events import build_change_event, make_event_fingerprint

class MonitoringPolicyTests(unittest.TestCase):
    def test_technical_changes_are_ignored(self):
        result = classify_changed_fields(["updated_at", "first_seen_at", "search_number"])
        self.assertFalse(result.significant)
        self.assertEqual(result.categories, ())
        self.assertEqual(result.fields, ())

    def test_business_changes_are_classified(self):
        result = classify_changed_fields(["price", "deadline", "price", "raw_data"])
        self.assertTrue(result.significant)
        self.assertEqual(result.categories, ("Цена", "Срок подачи", "Документация/условия"))
        self.assertEqual(result.fields, ("price", "deadline", "price", "raw_data"))

    def test_snapshot_diff_is_deterministic(self):
        previous = {"price": 100, "deadline": "2026-09-20", "raw_data": {"a": 1}}
        current = {"price": 120, "deadline": "2026-09-19", "raw_data": {"a": 2}}
        a = significant_diff(previous, current)
        b = significant_diff(current, previous)
        self.assertTrue(a.significant)
        self.assertEqual(a.categories, b.categories)
        self.assertEqual(a.fields, b.fields)

    def test_fingerprint_is_stable_and_changes_with_snapshot(self):
        snapshot = {"price": 100, "deadline": "2026-09-20"}
        a = make_event_fingerprint("eis:1", "tender_changed", snapshot, ("Цена",))
        b = make_event_fingerprint("eis:1", "tender_changed", snapshot, ("Цена",))
        c = make_event_fingerprint("eis:1", "tender_changed", {"price": 101}, ("Цена",))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_event_has_stable_identity(self):
        snapshot = {"price": 100}
        event = build_change_event(7, "b2b:42", snapshot, ("Цена",))
        self.assertEqual(event.tender_id, 7)
        self.assertEqual(len(event.fingerprint), 64)

if __name__ == "__main__":
    unittest.main()
