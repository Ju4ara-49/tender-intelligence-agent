from __future__ import annotations

import unittest

from src.collectors.fabrikant_v3 import FabrikantV3Collector


class FabrikantV3ContractTests(unittest.TestCase):
    def test_223_relative_procedure_link_keeps_registry_fields(self) -> None:
        collector = FabrikantV3Collector()
        collector.BASE_URL = "https://soap2.fabrikant.ru/223/catalog/procedure/published"
        html = """
        <html><body>
          <table>
            <tr>
              <th>№ извещения</th>
              <th>Наименование</th>
              <th>НМЦ</th>
              <th>Заказчик</th>
              <th>Дата публикации</th>
              <th>Завершение подачи</th>
            </tr>
            <tr>
              <td>223000123456789</td>
              <td><a href="/223/procedure/123456789">Поставка подшипников</a></td>
              <td>1 234 567,89 руб.</td>
              <td>АО Тестовый заказчик</td>
              <td>12.09.2026 10:15</td>
              <td>20.09.2026 18:00</td>
            </tr>
          </table>
        </body></html>
        """

        results = collector._parse_results(html)

        self.assertEqual(len(results), 1)
        tender = results[0]
        self.assertEqual(tender.external_id, "123456789")
        self.assertEqual(tender.title, "Поставка подшипников")
        self.assertEqual(tender.customer, "АО Тестовый заказчик")
        self.assertEqual(tender.price, 1234567.89)
        self.assertEqual(tender.published_at.year, 2026)
        self.assertEqual(tender.deadline.day, 20)
        self.assertEqual(tender.law_type, "223-ФЗ")
        self.assertEqual(tender.raw_data["search_row"]["mapping"]["customer"], 3)
        self.assertIn("123456789", collector._urls)
        self.assertEqual(collector._urls["123456789"], "https://soap2.fabrikant.ru/223/procedure/123456789")


if __name__ == "__main__":
    unittest.main()
