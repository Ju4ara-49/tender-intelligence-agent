from __future__ import annotations

import unittest

from src.collectors.browser_public import RtsTenderCollector, TmkCollector


class BrowserPublicParserTests(unittest.TestCase):
    HTML = """
    <html><body>
      <div data-href="/poisk/id/1234567/">
        <span>Поставка подшипников</span>
      </div>
      <button data-url="/purchase/7654321/">
        Поставка запасных частей
      </button>
      <div routerlink="/procedure/9876543/">
        Закупка оборудования
      </div>
    </body></html>
    """

    def test_rts_parser_accepts_data_href(self) -> None:
        collector = RtsTenderCollector()
        results = collector._parse_results(self.HTML)
        ids = {item.external_id for item in results}
        self.assertIn("1234567", ids)
        self.assertIn("7654321", ids)
        self.assertIn("9876543", ids)

    def test_tmk_parser_accepts_spa_navigation_attributes(self) -> None:
        collector = TmkCollector()
        results = collector._parse_results(self.HTML)
        self.assertEqual(
            {item.external_id for item in results},
            {"1234567", "7654321", "9876543"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
