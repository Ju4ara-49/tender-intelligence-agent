import unittest

from src.collectors.fabrikant import FabrikantCollector


class TestFabrikantFields(unittest.TestCase):
    def test_extracts_subject_customer_region_and_dates(self):
        html = """
        <html><body>
          <h1>Сведения о закупке 0803300226124000074</h1>
          <table>
            <tr><td>Предмет закупки</td><td>Подшипники прочие, зубчатые колеса, зубчатые передачи и элементы приводов</td></tr>
            <tr><td>Заказчик</td><td>МКУ «УХТО администрации Дербентского района»</td></tr>
            <tr><td>Регион</td><td>Республика Дагестан</td></tr>
            <tr><td>Дата публикации</td><td>08.12.2024</td></tr>
            <tr><td>Окончание подачи заявок</td><td>08.12.2024 12:00</td></tr>
          </table>
        </body></html>
        """
        tender = FabrikantCollector()._parse_detail(html, "0803300226124000074", "https://soap4.fabrikant.ru/44/procedure/ezt/0803300226124000074")
        self.assertEqual(tender.title, "Подшипники прочие, зубчатые передачи и элементы приводов".replace("зубчатые передачи", "зубчатые колеса, зубчатые передачи"))
        self.assertEqual(tender.customer, "МКУ «УХТО администрации Дербентского района»")
        self.assertEqual(tender.region, "Республика Дагестан")
        self.assertEqual(tender.published_at.strftime("%d.%m.%Y"), "08.12.2024")
        self.assertEqual(tender.deadline.strftime("%d.%m.%Y %H:%M"), "08.12.2024 12:00")

    def test_generic_h1_is_not_used_when_subject_exists(self):
        html = """
        <h1>Сведения о закупке 0318200023426000183</h1>
        <div>Наименование закупки: Множественные электролиты ИВД, набор, ион-селективные электроды</div>
        <div>Заказчик: ГБУЗ «Инфекционная больница №4»</div>
        <div>Место поставки: Краснодарский край</div>
        <div>Дата размещения: 23.08.2026</div>
        <div>Срок подачи заявок: 30.08.2026 10:00</div>
        """
        tender = FabrikantCollector()._parse_detail(html, "0318200023426000183", "https://soap4.fabrikant.ru/44/procedure/ezt/0318200023426000183")
        self.assertIn("Множественные электролиты", tender.title)
        self.assertEqual(tender.customer, "ГБУЗ «Инфекционная больница №4»")
        self.assertEqual(tender.region, "Краснодарский край")
        self.assertIsNotNone(tender.published_at)
        self.assertIsNotNone(tender.deadline)


if __name__ == "__main__":
    unittest.main()
