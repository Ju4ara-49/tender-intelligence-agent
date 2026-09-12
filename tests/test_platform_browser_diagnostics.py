from __future__ import annotations

import unittest

from tests.platform_browser_diagnostics import extract_result_evidence


class PlatformBrowserDiagnosticsTests(unittest.TestCase):
    def test_explicit_zero_result_is_valid_evidence(self) -> None:
        evidence = extract_result_evidence("Реестр опубликованных закупок. Всего: 0")
        self.assertEqual(evidence["result_count"], 0)
        self.assertEqual(evidence["result_count_evidence"], "Всего: 0")

    def test_explicit_positive_result_count_is_detected(self) -> None:
        evidence = extract_result_evidence("Параметры поиска. Всего: 13 процедур")
        self.assertEqual(evidence["result_count"], 13)

    def test_active_lots_count_is_detected(self) -> None:
        evidence = extract_result_evidence("Актуальных лотов: 8 181")
        self.assertEqual(evidence["result_count"], 8181)

    def test_missing_result_count_returns_unknown(self) -> None:
        evidence = extract_result_evidence("Форма поиска загружена")
        self.assertIsNone(evidence["result_count"])
        self.assertIsNone(evidence["result_count_evidence"])


if __name__ == "__main__":
    unittest.main()
