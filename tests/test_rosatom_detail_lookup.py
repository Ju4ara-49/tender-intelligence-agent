from __future__ import annotations

import unittest

from src.collectors.rosatom import RosatomCollector
from src.models.tender import Tender


class RosatomDetailLookupTests(unittest.TestCase):
    def test_numeric_external_id_is_a_verified_search_match(self) -> None:
        tender = Tender(
            platform="rosatom",
            external_id="233152",
            title="Право заключения договора на поставку подшипников",
            url="https://zakupki.rosatom.ru/?link=published_procurements",
            description="Право заключения договора на поставку подшипников",
        )
        self.assertTrue(RosatomCollector._tender_matches_query(tender, "233152"))

    def test_numeric_external_id_does_not_make_other_tender_match(self) -> None:
        tender = Tender(
            platform="rosatom",
            external_id="233153",
            title="Поставка кабельной продукции",
            url="https://zakupki.rosatom.ru/?link=published_procurements",
            description="Поставка кабельной продукции",
        )
        self.assertFalse(RosatomCollector._tender_matches_query(tender, "233152"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
