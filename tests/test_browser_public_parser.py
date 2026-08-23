from __future__ import annotations

import unittest

from src.collectors.browser_public import RtsTenderCollector, TmkCollector


class BrowserPublicParserTests(unittest.TestCase):
    HTML = """
    <html><body>
      <div data-href="/poisk/id/1234567/"><span>Поставка подшипников</span></div>
      <button data-url="/purchase/7654321/">Поставка запасных частей</button>
      <div routerlink="/procedure/9876543/">Закупка оборудования</div>
      <div onclick="location.href='/tender/11223344/'"><span>Закупка муфт</span></div>
    </body></html>
    """

    def test_rts_parser_accepts_spa_navigation_attributes(self) -> None:
        collector = RtsTenderCollector()
        results = collector._parse_results(self.HTML)
        self.assertEqual(
            {item.external_id for item in results},
            {"1234567", "7654321", "9876543", "11223344"},
        )

    def test_tmk_parser_accepts_spa_navigation_attributes(self) -> None:
        collector = TmkCollector()
        results = collector._parse_results(self.HTML)
        self.assertEqual(
            {item.external_id for item in results},
            {"1234567", "7654321", "9876543", "11223344"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
