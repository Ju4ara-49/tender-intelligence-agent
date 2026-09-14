from __future__ import annotations

import unittest

from src.collectors.browser_public import RtsTenderCollector, TmkCollector
from src.collectors.browser_public_reliable import ReliableRosatomCollector


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

    def test_rosatom_reliable_collector_enables_published_listing_fallback(self) -> None:
        collector = ReliableRosatomCollector()
        self.assertTrue(collector.ALLOW_PUBLISHED_LISTING_FALLBACK)

    def test_rosatom_parser_accepts_published_registry_links(self) -> None:
        from src.collectors.rosatom import RosatomCollector

        html = """
        <html><body>
          <a href="/Web.aspx?link=procurements&obj_id=ABC123=">Поставка подшипников</a>
          <a href="/Web.aspx?link=procurements&obj_id=DEF456=">Поставка запасных частей</a>
        </body></html>
        """
        results = RosatomCollector()._parse_results(html)
        self.assertEqual(
            {item.external_id for item in results},
            {"ABC123=", "DEF456="},
        )

    def test_rosatom_parser_reads_current_published_table_rows(self) -> None:
        from src.collectors.rosatom import RosatomCollector

        html = """
        <html><body>
          <table>
            <tr>
              <th>Номер закупки</th><th>Предмет договора</th><th>НМЦ, руб</th>
              <th>Организатор закупки</th><th>Дата публикации</th>
              <th>Дата окончания подачи заявок/подведения итогов</th>
              <th>Площадка размещения закупок</th><th>Регион поставки</th>
            </tr>
            <tr>
              <td>233152 (5101874)</td>
              <td>Право заключения договора на поставка подшипников</td>
              <td>9 377 116,42</td>
              <td>ООО "АРМЗ Сервис"</td>
              <td>27.08.2026</td>
              <td>Этап 1: 11.09.2026 10:00:00</td>
              <td></td>
              <td>Томская область</td>
            </tr>
          </table>
        </body></html>
        """
        results = RosatomCollector()._parse_results(html)
        self.assertEqual(len(results), 1)
        tender = results[0]
        self.assertEqual(tender.external_id, "233152")
        self.assertEqual(tender.raw_data["official_number"], "5101874")
        self.assertEqual(tender.customer, 'ООО "АРМЗ Сервис"')
        self.assertEqual(tender.region, "Томская область")
        self.assertAlmostEqual(tender.price or 0, 9377116.42)
        self.assertIsNotNone(tender.published_at)
        self.assertIsNotNone(tender.deadline)
        self.assertTrue(tender.raw_data["discovery_only"])

    def test_rosatom_parser_reads_tbody_rows_after_thead(self) -> None:
        from src.collectors.rosatom import RosatomCollector

        html = """
        <table>
          <thead><tr>
            <th>Номер закупки</th><th>Предмет договора</th><th>НМЦ, руб</th>
            <th>Организатор закупки</th><th>Дата публикации</th>
            <th>Дата окончания подачи заявок/подведения итогов</th>
            <th>Площадка размещения закупок</th><th>Регион поставки</th>
          </tr></thead>
          <tbody><tr>
            <td>227168 (5090323)</td>
            <td>Право заключения договора на подшипники специальные</td>
            <td>6 946 112,70</td>
            <td>АО "ПРОМИНН"</td>
            <td>17.08.2026</td>
            <td>Этап 1: 11.09.2026 10:00:00</td>
            <td>РТС-Тендер</td>
            <td>Томская область</td>
          </tr></tbody>
        </table>
        """
        results = RosatomCollector()._parse_results(html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].external_id, "227168")
        self.assertEqual(results[0].raw_data["official_number"], "5090323")
        self.assertEqual(results[0].raw_data["procurement_platform"], "РТС-Тендер")
        self.assertIsNotNone(results[0].deadline)


if __name__ == "__main__":
    unittest.main(verbosity=2)
