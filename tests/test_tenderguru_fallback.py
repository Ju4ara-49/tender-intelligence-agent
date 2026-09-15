from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from src.collectors.tenderguru_fallback import matches_keyword, search


class TenderGuruFallbackTests(unittest.TestCase):
    def test_keyword_morphology(self) -> None:
        self.assertTrue(matches_keyword("Лебёдки электрические канатные", "лебедка"))
        self.assertTrue(matches_keyword("Подшипники роликовые", "подшипник"))
        self.assertTrue(matches_keyword("Станки токарные", "станок"))
        self.assertFalse(matches_keyword("Станция насосная", "станок"))

    @patch("src.collectors.tenderguru_fallback._SESSION.get")
    def test_rts_filters_to_rts_listings(self, get: Mock) -> None:
        get.return_value = Mock(
            raise_for_status=lambda: None,
            text="""
              <a href="/tender/123">Поставка станка</a>
              <div>Поставка станка Номер тендера: 123 Электронная площадка: РТС-тендер</div>
              <a href="/tender/124">Поставка станка</a>
              <div>Поставка станка Номер тендера: 124 Электронная площадка: B2B-Center</div>
            """,
        )
        result = search(platform="rts_tender", keyword="станок", max_pages=1)
        self.assertEqual([x.external_id for x in result], ["123"])
        self.assertEqual(result[0].raw_data["source"], "tenderguru_public_fallback")

    @patch("src.collectors.tenderguru_fallback._SESSION.get")
    def test_eis_keeps_44_and_223_listings(self, get: Mock) -> None:
        get.return_value = Mock(
            raise_for_status=lambda: None,
            text="""
              <a href="/tender/201">Станок для школы</a>
              <div>Станок для школы Госзакупка по 44-ФЗ</div>
              <a href="/tender/202">Станок для завода</a>
              <div>Станок для завода По 223-ФЗ закону</div>
              <a href="/tender/203">Станок коммерческий</a>
              <div>Станок коммерческий Электронная площадка: B2B-Center</div>
            """,
        )
        result = search(platform="eis", keyword="станок", max_pages=1)
        self.assertEqual({x.external_id for x in result}, {"201", "202"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
