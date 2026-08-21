"""Проверки нормализации B2B-Center на сохранённой реальной выдаче."""

from __future__ import annotations

from pathlib import Path
import unittest

from src.collectors.b2b_center import B2BCenterCollector
from src.models.tender import Tender


class B2BCenterCollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.collector = B2BCenterCollector({"request_delay_seconds": 0})
        html = Path("b2b_test.html").read_text(encoding="utf-8")
        cls.results = cls.collector._parse_search_html(
            html,
            "подшипники",
        )

    def test_import_and_platform_identifier(self) -> None:
        self.assertEqual(self.collector.platform, "b2b_center")

    def test_search_result_is_normalized_tender(self) -> None:
        self.assertGreaterEqual(len(self.results), 1)
        self.assertTrue(all(isinstance(item, Tender) for item in self.results))

    def test_result_has_identifier_title_url_and_dates(self) -> None:
        tender = self.results[0]

        self.assertTrue(tender.external_id.isdigit())
        self.assertTrue(tender.title)
        self.assertFalse(
            tender.title.lower().startswith(
                ("тендер", "запрос предложений", "аукцион", "конкурс")
            )
        )
        self.assertTrue(tender.url.startswith("https://www.b2b-center.ru/"))
        self.assertIn(f"tender-{tender.external_id}", tender.url)
        self.assertIsNotNone(tender.published_at)
        self.assertIsNotNone(tender.deadline)
        self.assertIsNotNone(tender.published_at.tzinfo)
        self.assertIsNotNone(tender.deadline.tzinfo)

    def test_price_and_commercial_condition_extractors(self) -> None:
        self.assertEqual(
            self.collector._extract_price("Общая стоимость закупки: 12 345,67 руб."),
            12345.67,
        )

        conditions = self.collector._extract_commercial_conditions(
            "Условия оплаты: 100% по факту поставки в течении "
            "30 календарных дней."
        )
        self.assertFalse(conditions["advance_required"])
        self.assertEqual(conditions["postpayment_days"], 30)

    def test_title_cleanup_removes_service_prefix(self) -> None:
        self.assertEqual(
            self.collector._clean_procedure_title(
                "Запрос предложений № 4571794 — Поставка подшипников",
                "4571794",
            ),
            "Поставка подшипников",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
