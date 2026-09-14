from __future__ import annotations

import json
import unittest
from pathlib import Path

import tests.platform_browser_diagnostics as diagnostics

from tests.platform_browser_diagnostics import classify_http_access, extract_result_evidence, has_published_listing_evidence, is_external_challenge


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


    def test_javascript_cookie_challenge_is_external_access(self) -> None:
        body = "Пожалуйста подождите. Для работы с сайтом необходимы включенные Javascript и Cookies."
        self.assertTrue(is_external_challenge(body))
        self.assertFalse(is_external_challenge("Параметры поиска Поиск закупок"))
        self.assertTrue(is_external_challenge("Web Page Blocked! The URL you requested has been blocked. Attack ID: 20000051"))

    def test_windows_stdout_is_forced_to_utf8(self) -> None:
        source = Path(diagnostics.__file__).read_text(encoding="utf-8")
        self.assertIn('sys.stdout.reconfigure(encoding="utf-8", errors="replace")', source)


    def test_summary_loop_skips_failure_metadata(self) -> None:
        source = Path(diagnostics.__file__).read_text(encoding="utf-8")
        self.assertIn('"internal_failures", "access_blocks"', source)
        self.assertIn('"hard_external_access"', source)

    def test_script_has_real_entrypoint_to_prevent_false_green(self) -> None:
        source = Path(diagnostics.__file__).read_text(encoding="utf-8")
        self.assertIn('if __name__ == "__main__":', source)
        self.assertIn("raise SystemExit(main())", source)

    def test_navigation_timeout_is_a_hard_external_failure(self) -> None:
        source = Path(diagnostics.__file__).read_text(encoding="utf-8")
        self.assertIn("PlaywrightTimeoutError", source)
        self.assertIn('"external_timeout"', source)
        self.assertIn('"external_access"', source)
        self.assertIn("access_blocks.append(message)", source)
        self.assertIn("ci_failures.append(message)", source)
        self.assertIn("HARD_EXTERNAL_ACCESS", source)
        self.assertIn("blocking_failures = list(internal_failures)", source)
        self.assertIn("if HARD_EXTERNAL_ACCESS:", source)

    def test_report_contract_keeps_external_failures_in_ci_gate(self) -> None:
        report = {
            "failures": ["rts_tender: external navigation timeout"],
            "ci_failures": ["rts_tender: external navigation timeout"],
            "access_blocks": ["rts_tender: external navigation timeout"],
            "access_block_count": 1,
            "ci_failure_count": 1,
            "internal_failures": [],
            "hard_external_access": False,
        }
        serialized = json.dumps(report, ensure_ascii=False)
        loaded = json.loads(serialized)
        self.assertEqual(loaded["access_block_count"], 1)
        self.assertEqual(loaded["ci_failure_count"], 1)
        self.assertEqual(loaded["ci_failures"], loaded["access_blocks"])
        self.assertEqual(loaded["internal_failures"], [])
        self.assertFalse(loaded["hard_external_access"])


if __name__ == "__main__":
    unittest.main()
