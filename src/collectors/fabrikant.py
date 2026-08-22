"""Public collector for the Fabrikant electronic trading platform."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.collectors.browser_public import _BrowserTenderCollector
from src.models.tender import Tender

logger = logging.getLogger(__name__)


class FabrikantCollector(_BrowserTenderCollector):
    """Search public Fabrikant procurement registers (44-FZ and 223-FZ)."""

    platform = "fabrikant"
    # The 223-FZ register exposes a public keyword search and is also the
    # section where Fabrikant/Rosatom procedures are published.
    BASE_URL = "https://soap2.fabrikant.ru/223/catalog/procedure/published"
    SEARCH_HINTS = ("Поиск", "Найти", "Применить")
    LINK_HINTS = ("/223/procedure/", "/223/catalog/procedure", "procedure")

    def search(self, keywords: list[str], since=None) -> list[Tender]:
        """Search both public Fabrikant sections for each keyword."""
        terms = [str(x).strip() for x in keywords if str(x).strip()]
        if not terms:
            return []

        merged: dict[str, Tender] = {}
        for base_url in (
            "https://soap2.fabrikant.ru/223/catalog/procedure/published",
            "https://soap4.fabrikant.ru/44/catalog/procedure",
        ):
            self.BASE_URL = base_url
            self._urls = {}
            for term in terms:
                results = self._search_one(term)
                for tender in results:
                    merged[tender.unique_key] = tender
                    if len(merged) >= self.max_results:
                        break
                if len(merged) >= self.max_results:
                    break
            if len(merged) >= self.max_results:
                break

        logger.info("fabrikant: найдено %d уникальных процедур", len(merged))
        return list(merged.values())[: self.max_results]

    def _parse_results(self, html: str) -> list[Tender]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[Tender] = []
        seen: set[str] = set()
        base_host = urlparse(self.BASE_URL).netloc.lower()

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", "")).strip()
            if not href:
                continue
            from urllib.parse import urljoin
            href = urljoin(self.BASE_URL, href)
            parsed = urlparse(href)
            if parsed.netloc.lower() != base_host:
                continue
            low = href.lower()
            if "/procedure/" not in low:
                continue

            title = " ".join(anchor.stripped_strings)
            if not title or len(title) < 5:
                continue
            external_id = self._extract_id(href, title)
            if not external_id or external_id in seen:
                continue

            seen.add(external_id)
            self._urls[external_id] = href
            results.append(
                Tender(
                    platform=self.platform,
                    external_id=external_id,
                    title=title[:1000],
                    url=href,
                    description=title,
                    raw_data={"source": self.BASE_URL},
                )
            )
        return results
