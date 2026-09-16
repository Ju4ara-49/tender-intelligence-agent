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

    def test_keyword_morphology_is_insensitive_to_query_word_form(self) -> None:
        self.assertTrue(matches_keyword("Продаётся один станок", "станки"))
        self.assertTrue(matches_keyword("Куплю один подшипника", "подшипники"))
        self.assertTrue(matches_keyword("Закупка лебедок партией", "лебедка"))

    @patch("src.collectors.tenderguru_fallback._SESSION.get")
    def test_search_resolves_topic_for_declined_query_form(self, get: Mock) -> None:
        get.return_value = Mock(
            raise_for_status=lambda: None,
            text='<div>Поставка станка Номер тендера: 301 <a href="/tender/301">Поставка станка</a></div>',
        )
        result = search(platform="b2b_center", keyword="станки", max_pages=1)
        self.assertEqual([x.external_id for x in result], ["301"])
        self.assertTrue(get.called)

    @patch("src.collectors.tenderguru_fallback._SESSION.get")
    def test_rts_filters_to_rts_listings(self, get: Mock) -> None:
        get.return_value = Mock(
            raise_for_status=lambda: None,
            text="""
              <div>Поставка станка Номер тендера: 123 Электронная площадка: РТС-тендер <a href="/tender/123">Поставка станка</a></div>
              <div>Поставка станка Номер тендера: 124 Электронная площадка: B2B-Center <a href="/tender/124">Поставка станка</a></div>
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
              <div>Станок для школы Госзакупка по 44-ФЗ <a href="/tender/201">Станок для школы</a></div>
              <div>Станок для завода По 223-ФЗ закону <a href="/tender/202">Станок для завода</a></div>
              <div>Станок коммерческий Электронная площадка: B2B-Center <a href="/tender/203">Станок коммерческий</a></div>
            """,
        )
        result = search(platform="eis", keyword="станок", max_pages=1)
        self.assertEqual({x.external_id for x in result}, {"201", "202"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
