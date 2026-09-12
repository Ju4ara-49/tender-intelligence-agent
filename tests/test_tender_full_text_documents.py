from __future__ import annotations

import unittest

from src.models.tender import Tender


class TenderFullTextDocumentTests(unittest.TestCase):
    def test_full_text_includes_document_metadata(self) -> None:
        tender = Tender(
            platform="test",
            external_id="1",
            title="Поставка",
            url="https://example.invalid/1",
            documents=[
                {"name": "Техническое задание на поставку подшипников", "url": "https://example.invalid/doc.pdf"},
            ],
        )
        self.assertIn("Техническое задание на поставку подшипников", tender.full_text)

    def test_full_text_includes_indexed_document_text(self) -> None:
        tender = Tender(
            platform="test",
            external_id="2",
            title="Закупка оборудования",
            url="https://example.invalid/2",
            raw_data={"document_search_text": "Требования к подшипникам SKF и аналогам"},
        )
        self.assertIn("Требования к подшипникам SKF и аналогам", tender.full_text)

    def test_document_text_can_supply_commercial_terms(self) -> None:
        tender = Tender(
            platform="test",
            external_id="3",
            title="Закупка",
            url="https://example.invalid/3",
            raw_data={"document_text": "Предоплата 30%. Отсрочка платежа 45 календарных дней."},
        )
        self.assertEqual(tender.advance_percent, 30.0)
        self.assertEqual(tender.postpayment_days, 45)


if __name__ == "__main__":
    unittest.main()
