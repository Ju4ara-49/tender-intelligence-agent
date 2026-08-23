import unittest
from datetime import datetime, timezone

from src.filters.keyword_filter import KeywordFilter
from src.models.tender import Tender


class B2BQualityGateTests(unittest.TestCase):
    def _tender(self, **overrides):
        data = dict(
            platform="b2b_center",
            external_id="4564558",
            title="Подшипники",
            url="https://www.b2b-center.ru/app/market/tender-4564558/",
            customer="Заказчик",
            price=100000.0,
            deadline=datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
            raw_data={"details_loaded": True},
        )
        data.update(overrides)
        return Tender(**data)

    def test_incomplete_b2b_details_are_rejected(self):
        tender = self._tender(customer="", price=None, deadline=None)
        filt = KeywordFilter(include=["подшипник"], exclude=[])
        self.assertFalse(filt.matches_strict(tender))

    def test_b2b_without_loaded_details_is_rejected(self):
        tender = self._tender(raw_data={})
        filt = KeywordFilter(include=["подшипник"], exclude=[])
        self.assertFalse(filt.matches_strict(tender))

    def test_complete_b2b_tender_is_kept(self):
        tender = self._tender()
        filt = KeywordFilter(include=["подшипник"], exclude=[])
        self.assertTrue(filt.matches_strict(tender))

    def test_other_platforms_are_not_subject_to_b2b_gate(self):
        tender = self._tender(platform="eis_zakupki", customer="", price=None, deadline=None, raw_data={})
        filt = KeywordFilter(include=["подшипник"], exclude=[])
        self.assertTrue(filt.matches_strict(tender))


if __name__ == "__main__":
    unittest.main()
