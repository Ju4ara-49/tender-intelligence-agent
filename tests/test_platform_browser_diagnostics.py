from __future__ import annotations

import json
import unittest
from pathlib import Path

import tests.platform_browser_diagnostics as diagnostics

from tests.platform_browser_diagnostics import classify_http_access, extract_result_evidence, has_published_listing_evidence


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

    def test_http_401_403_429_are_access_blocks(self) -> None:
        for status in (401, 403, 429):
            with self.subTest(status=status):
                self.assertEqual(classify_http_access(status), "access_block")

    def test_normal_http_status_is_not_access_block(self) -> None:
        self.assertIsNone(classify_http_access(200))
        self.assertIsNone(classify_http_access(500))
        self.assertIsNone(classify_http_access(None))

    def test_supported_targets_are_all_covered(self) -> None:
        self.assertEqual(
            set(diagnostics.TARGETS),
            {
                "eis",
                "b2b_center",
                "fabrikant_223",
                "fabrikant_44",
                "rts_tender",
                "tmk",
                "rosatom",
            },
        )

    def test_rosatom_published_listing_is_valid_fallback_evidence(self) -> None:
        links = [{"text": "Закупка", "href": "https://zakupki.rosatom.ru/Web.aspx?link=procurements&obj_id=ABC123="}]
        self.assertTrue(has_published_listing_evidence("rosatom", links))
        self.assertFalse(has_published_listing_evidence("tmk", links))

    def test_script_has_real_entrypoint_to_prevent_false_green(self) -> None:
        source = Path(diagnostics.__file__).read_text(encoding="utf-8")
        self.assertIn('if __name__ == "__main__":', source)
        self.assertIn("raise SystemExit(main())", source)

    def test_navigation_timeout_is_documented_as_external_access(self) -> None:
        source = Path(diagnostics.__file__).read_text(encoding="utf-8")
        self.assertIn("PlaywrightTimeoutError", source)
        self.assertIn('"external_timeout"', source)
        self.assertIn('"external_access"', source)
        self.assertIn("access_blocks.append(message)", source)
        self.assertIn("return 1 if ci_failures else 0", source)

    def test_report_contract_separates_access_blocks_from_ci_failures(self) -> None:
        report = {
            "failures": ["eis: WAF or access block", "rts_tender: external navigation timeout"],
            "ci_failures": [],
            "access_blocks": ["eis: WAF or access block", "rts_tender: external navigation timeout"],
            "access_block_count": 2,
            "ci_failure_count": 0,
        }
        serialized = json.dumps(report, ensure_ascii=False)
        loaded = json.loads(serialized)
        self.assertEqual(loaded["access_block_count"], 2)
        self.assertEqual(loaded["ci_failure_count"], 0)
        self.assertEqual(loaded["ci_failures"], [])
        self.assertEqual(len(loaded["access_blocks"]), 2)


if __name__ == "__main__":
    unittest.main()
