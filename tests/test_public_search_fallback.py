import unittest
from unittest.mock import patch

from src.collectors import public_search_fallback


BING_HTML = """
<html><body><li class='b_algo'>
<h2><a href='https://www.b2b-center.ru/tenders/123'>Закупка подшипников для оборудования</a></h2>
<div class='b_caption'><p>Поставка подшипников, срок поставки и условия.</p></div>
</li></body></html>
"""


class TestPublicSearchFallback(unittest.TestCase):
    def test_bing_result_is_restricted_to_requested_platform_and_keyword(self):
        rows = public_search_fallback._bing_results(BING_HTML, "b2b_center", "подшипник")
        self.assertEqual(len(rows), 1)
        self.assertIn("b2b-center.ru", rows[0][0])
        self.assertIn("подшипников", rows[0][1].casefold())

    def test_search_creates_provenance_and_stable_id(self):
        with patch.object(public_search_fallback, "_request", return_value=BING_HTML):
            result = public_search_fallback.search(
                platform="b2b_center",
                keyword="подшипник",
                timeout=1,
                max_results=5,
            )
        self.assertEqual(len(result), 1)
        tender = result[0]
        self.assertEqual(tender.platform, "b2b_center")
        self.assertTrue(tender.external_id.startswith("public-search-"))
        self.assertEqual(tender.raw_data["source"], "public_search_engine_fallback")
        self.assertEqual(tender.raw_data["source_engine"], "bing")
        self.assertFalse(tender.raw_data["details_loaded"])

    def test_yandex_is_used_when_bing_fails(self):
        yandex_html = """
        <html><body><li class='serp-item'>
          <a href='https://www.fabrikant.ru/procedure/456'><h2>Станок токарный</h2></a>
          <div>Закупка станка токарного оборудования</div>
        </li></body></html>
        """
        def request(url, timeout):
            if "bing.com" in url:
                raise RuntimeError("bing unavailable")
            if "yandex.ru" in url:
                return yandex_html
            raise AssertionError("google must not be reached after Yandex succeeds")

        with patch.object(public_search_fallback, "_request", side_effect=request):
            result = public_search_fallback.search(
                platform="fabrikant",
                keyword="станок",
                timeout=1,
                max_results=5,
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].raw_data["source_engine"], "yandex")

    def test_google_is_used_when_bing_and_yandex_fail(self):
        google_html = """
        <html><body><div><a href='https://www.fabrikant.ru/procedure/456'>Станок токарный</a></div></body></html>
        """
        def request(url, timeout):
            if "bing.com" in url or "yandex.ru" in url:
                raise RuntimeError("search engine unavailable")
            return google_html

        with patch.object(public_search_fallback, "_request", side_effect=request):
            result = public_search_fallback.search(
                platform="fabrikant",
                keyword="станок",
                timeout=1,
                max_results=5,
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].raw_data["source_engine"], "google")

    def test_unrelated_domain_is_rejected(self):
        html = """
        <li class='b_algo'>
          <h2><a href='https://example.com/tender/1'>Подшипник</a></h2>
          <div class='b_caption'><p>Подшипник</p></div>
        </li>
        """
        self.assertEqual(public_search_fallback._bing_results(html, "b2b_center", "подшипник"), [])


if __name__ == "__main__":
    unittest.main()
