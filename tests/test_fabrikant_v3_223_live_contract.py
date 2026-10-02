from __future__ import annotations

import unittest

from src.collectors.fabrikant_v3 import FabrikantV3Collector


# Captured from the live Fabrikant 223-FZ register
# (https://soap2.fabrikant.ru/223/catalog/procedure/published?q=поставка).
# The 223 registry table has no separate "№ извещения" column: the notice number
# is embedded inside the "Наименование закупки (номер извещения)" title cell, and
# the detail link is a 4-digit etp-ets id (/223/zp/procedure/view/2003) that the
# real notice number (e.g. 32008909965) only appears in the cell text.
FABRIKANT_223_HTML = """
<html><body>
  <table>
    <tr>
      <th>Тип</th>
      <th>Наименование закупки (номер извещения)</th>
      <th>Наименование лота (номер лота)</th>
      <th>Начальная (макс.) цена</th>
      <th>Организатор закупки</th>
      <th>Заказчик</th>
      <th>Дата и время публикации</th>
      <th>Дата и время окончания подачи заявок</th>
      <th>Статус</th>
      <th>Действия</th>
    </tr>
    <tr>
      <td>ЗП</td>
      <td><a href="/223/zp/procedure/view/2003/">Поставка угля бурого 2 БР</a> 32008909965</td>
      <td>Поставка угля бурого марки 2 БР (Лот №1)</td>
      <td>3 130 625.40 RUB</td>
      <td>МАЗАНОВСКОЕ УНИТАРНОЕ МУНИЦИПАЛЬНОЕ ПРЕДПРИЯТИЕ "ТРАНСПОРТНОЕ"</td>
      <td>МАЗАНОВСКОЕ УНИТАРНОЕ МУНИЦИПАЛЬНОЕ ПРЕДПРИЯТИЕ "ТРАНСПОРТНОЕ"</td>
      <td>21.02.2020 11:50:00 (MSK+00:00)</td>
      <td>04.03.2020 18:00:00 (MSK+00:00)</td>
      <td>Прием заявок</td>
      <td></td>
    </tr>
    <tr>
      <td>ЭА2</td>
      <td><a href="/223/ea2/procedure/view/4601/">поставка расходных материалов для лаборатории</a> 31806781286</td>
      <td>поставка расходных материалов для лаборатории (Лот №1)</td>
      <td>142 415.35 RUB</td>
      <td>ГОСУДАРСТВЕННОЕ БЮДЖЕТНОЕ УЧРЕЖДЕНИЕ ЗДРАВООХРАНЕНИЯ "РОДИЛЬНЫЙ ДОМ" Г.МИХАЙЛОВКИ</td>
      <td>ГОСУДАРСТВЕННОЕ БЮДЖЕТНОЕ УЧРЕЖДЕНИЕ ЗДРАВООХРАНЕНИЯ "РОДИЛЬНЫЙ ДОМ" Г.МИХАЙЛОВКИ</td>
      <td>16.09.2019 10:13:16 (MSK+00:00)</td>
      <td>23.08.2018 09:00:00 (MSK+00:00)</td>
      <td>Прием заявок</td>
      <td></td>
    </tr>
    <tr>
      <td>ЗК</td>
      <td><a href="/223/zk/procedure/view/6699/">Поставка автомобиля</a> 31908284337</td>
      <td>Поставка автомобиля (Лот №1)</td>
      <td>629 800.00 RUB</td>
      <td>ГОСУДАРСТВЕННОЕ БЮДЖЕТНОЕ УЧРЕЖДЕНИЕ РЕСПУБЛИКИ ДАГЕСТАН "РЕСПУБЛИКАНСКИЙ ПРОТИВОТУБЕРКУЛЕЗНЫЙ ДИСПАНСЕР"</td>
      <td>ГОСУДАРСТВЕННОЕ БЮДЖЕТНОЕ УЧРЕЖДЕНИЕ РЕСПУБЛИКИ ДАГЕСТАН "РЕСПУБЛИКАНСКИЙ ПРОТИВОТУБЕРКУЛЕЗНЫЙ ДИСПАНСЕР"</td>
      <td>12.09.2019 13:01:48 (MSK+00:00)</td>
      <td>18.09.2019 12:00:00 (MSK+00:00)</td>
      <td>Прием заявок</td>
      <td></td>
    </tr>
  </table>
</body></html>
"""

# The 44-FZ register keeps the legacy "№ извещения" column and 18-digit notice
# numbers in the detail link itself — this path must keep working unchanged.
FABRIKANT_44_HTML = """
<html><body>
  <table>
    <tr>
      <th>№ извещения</th>
      <th>Наименование</th>
      <th>НМЦ</th>
      <th>Заказчик</th>
    </tr>
    <tr>
      <td>0832500000526000074</td>
      <td><a href="/44/procedure/ezk21/0832500000526000074">Поставка подшипников</a></td>
      <td>2 500 000 руб.</td>
      <td>АО Стальресурс</td>
    </tr>
  </table>
</body></html>
"""


class FabrikantV3_223_FixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.collector = FabrikantV3Collector()
        self.collector.BASE_URL = "https://soap2.fabrikant.ru/223/catalog/procedure/published"

    def test_223_registry_header_is_recognized(self) -> None:
        """The 223-FZ table has 'Наименование закупки (номер извещения)' instead
        of a separate '№ извещения' column — it must still be detected."""
        from bs4 import BeautifulSoup
        from src.collectors.fabrikant_v2 import FabrikantV2Collector

        table = BeautifulSoup(FABRIKANT_223_HTML, "html.parser").find("table")
        header_info = FabrikantV2Collector._find_registry_header(table)
        self.assertIsNotNone(
            header_info,
            "223-FZ registry table must be recognized despite the combined title/notice header",
        )

    def test_223_results_are_not_silently_dropped(self) -> None:
        """Regression for the confirmed defect: live 223 rows are parseable and
        must yield tenders instead of an empty successful result."""
        results = self.collector._parse_results(FABRIKANT_223_HTML)
        self.assertEqual(len(results), 3)

    def test_223_uses_notice_number_not_short_link_id(self) -> None:
        """The 4-digit etp-ets id (2003) in the detail link must NOT be used as
        external_id; the real 11-digit notice number from the title cell must."""
        tender = self.collector._parse_results(FABRIKANT_223_HTML)[0]
        self.assertEqual(tender.external_id, "32008909965")
        self.assertNotIn("2003", tender.external_id)
        self.assertEqual(tender.law_type, "223-ФЗ")
        self.assertAlmostEqual(tender.price, 3_130_625.40, places=2)
        self.assertIn("МАЗАНОВСКОЕ", tender.customer)
        self.assertIn("/223/zp/procedure/view/2003", tender.url)
        self.assertTrue(tender.title.startswith("Поставка угля"))

    def test_223_all_rows_extracted_with_distinct_ids(self) -> None:
        tenders = self.collector._parse_results(FABRIKANT_223_HTML)
        ids = {t.external_id for t in tenders}
        self.assertEqual(ids, {"32008909965", "31806781286", "31908284337"})
        self.assertEqual(len(tenders), 3)
        for t in tenders:
            self.assertEqual(t.law_type, "223-ФЗ")
            self.assertIsNotNone(t.url)

    def test_223_url_is_mapped_for_detail_lookup(self) -> None:
        tenders = self.collector._parse_results(FABRIKANT_223_HTML)
        key = tenders[0].unique_key
        self.assertEqual(self.collector._urls["32008909965"], tenders[0].url)
        self.assertIn(key, (f"fabrikant:{t.external_id}" for t in tenders))

    def test_44_register_path_still_works(self) -> None:
        """Lock the legacy 44-FZ path (separate '№ извещения' column, 18-digit id)."""
        self.collector.BASE_URL = "https://soap4.fabrikant.ru/44/catalog/procedure"
        results = self.collector._parse_results(FABRIKANT_44_HTML)
        self.assertEqual(len(results), 1)
        tender = results[0]
        self.assertEqual(tender.external_id, "0832500000526000074")
        self.assertEqual(tender.law_type, "44-ФЗ")
        self.assertEqual(tender.title, "Поставка подшипников")
        self.assertEqual(tender.customer, "АО Стальресурс")
        self.assertEqual(tender.price, 2_500_000.0)


if __name__ == "__main__":
    unittest.main()
