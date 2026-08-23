from __future__ import annotations

import unittest
from datetime import datetime

from src.models.tender import Tender, TenderAnalysis
from src.notifications.telegram import TelegramNotifier


class TelegramPlatformLabelTests(unittest.TestCase):
    def test_alert_contains_human_readable_platform(self) -> None:
        tender = Tender(
            platform="b2b_center",
            external_id="1234567",
            title="Поставка подшипников",
            url="https://example.com/tender/1234567",
            customer="ООО Заказчик",
            price=100000,
            currency="RUB",
            deadline=datetime(2026, 8, 31),
        )
        analysis = TenderAnalysis(
            relevance_score=85,
            summary="Подходит.",
            recommendation="review",
            risks=[],
        )

        message = TelegramNotifier.format_message(tender, analysis)

        self.assertIn("Площадка:", message)
        self.assertIn("B2B-Center", message)

    def test_unknown_platform_is_not_hidden(self) -> None:
        tender = Tender(
            platform="new_platform",
            external_id="1",
            title="Тест",
            url="https://example.com/1",
        )
        analysis = TenderAnalysis(
            relevance_score=70,
            summary="Тест.",
            recommendation="review",
            risks=[],
        )

        message = TelegramNotifier.format_message(tender, analysis)

        self.assertIn("new_platform", message)


if __name__ == "__main__":
    unittest.main()
