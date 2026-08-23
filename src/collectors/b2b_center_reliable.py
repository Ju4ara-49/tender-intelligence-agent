"""Reliable public B2B-Center discovery adapter.

B2B-Center exposes a stable public /market/ search with f_keyword/searching
parameters and offset pagination. Discovery deliberately uses this public
endpoint instead of depending on the JS-heavy modern infinite-scroll UI.
Details continue to use the authenticated modern collector.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.collectors.b2b_center_modern import ModernB2BCenterCollector
from src.models.tender import Tender

logger = logging.getLogger(__name__)

BASE_URL = "https://www.b2b-center.ru"
LEGACY_SEARCH_URL = f"{BASE_URL}/market/"


class ReliableB2BCenterCollector(ModernB2BCenterCollector):
    """Broad, paginated discovery on the public B2B-Center market search."""

    platform = "b2b_center"

    def _load_search_page(self, keyword: str) -> str:
        """Collect multiple public result pages using offset pagination.

        B2B-Center's ``from`` parameter is an item offset, not a page number.
        A configured value of 1 must therefore never collapse discovery to one
        page: the reliable adapter enforces a broad lower bound and stops only
        on an actually empty/short page or the explicit safety cap.
        """
        configured_pages = int(self.config.get("max_pages", 20))
        max_pages = max(10, min(configured_pages, 50))
        page_size = max(20, min(int(self.config.get("page_size", 20)), 100))
        max_results = max(200, min(int(self.config.get("max_results", 500)), 2000))

        chunks: list[str] = []
        total_links = 0
        seen_ids: set[str] = set()

        for page_no in range(max_pages):
            offset = page_no * page_size
            if total_links >= max_results:
                break

            try:
                response = self._get(
                    LEGACY_SEARCH_URL,
                    params={
                        "f_keyword": keyword,
                        "searching": "1",
                        "company_type": "2",
                        "price_currency": "0",
                        "date": "1",
                        "trade": "buy",
                        "from": str(offset),
                    },
                )
                html = response.text or ""
                if not html:
                    logger.warning(
                        "B2B-Center: empty discovery response keyword=%r page=%d offset=%d",
                        keyword, page_no + 1, offset,
                    )
                    break

                soup = BeautifulSoup(html, "html.parser")
                links = soup.select("a.search-results-title[href], a[href*='/tender-']")
                page_ids: set[str] = set()
                for link in links:
                    href = str(link.get("href", ""))
                    match = re.search(r"tender-(\d+)", href, re.I)
                    if match:
                        page_ids.add(match.group(1))

                new_ids = page_ids - seen_ids
                seen_ids.update(page_ids)
                total_links += len(new_ids)
                chunks.append(html)

                logger.info(
                    "B2B-Center: reliable search keyword=%r page=%d offset=%d links=%d new=%d total_unique_links=%d",
                    keyword, page_no + 1, offset, len(links), len(new_ids), len(seen_ids),
                )

                if not links:
                    break
                # A short page is a strong end-of-pagination signal, but page 1
                # may be rendered with fewer links because some cards lack URLs.
                if page_no > 0 and len(links) < page_size:
                    break
                # If an entire page contains only IDs already seen, the server
                # ignored the offset; continuing would just duplicate page 1.
                if page_no > 0 and not new_ids:
                    logger.warning(
                        "B2B-Center: pagination offset=%d returned no new procedures; stopping",
                        offset,
                    )
                    break
            except Exception:
                logger.exception(
                    "B2B-Center: reliable search page failed keyword=%r page=%d",
                    keyword, page_no + 1,
                )
                break

            delay = float(self.config.get("request_delay_seconds", 0.5))
            if delay > 0:
                time.sleep(delay)

        logger.info(
            "B2B-Center: reliable search keyword=%r pages=%d procedure_links=%d",
            keyword, len(chunks), len(seen_ids),
        )
        return "\n".join(chunks)

    def _parse_search_html(
        self,
        html: str,
        keyword: str,
        since: datetime | None = None,
    ) -> list[Tender]:
        # Use the proven parser for normalization, then apply a transparent
        # relevance gate because the public endpoint can occasionally return
        # default/broad rows when a query is partially ignored.
        results = super()._parse_search_html(html, keyword, since)
        if not results:
            return results

        query_tokens = [
            self._normalize_query_token(token)
            for token in re.findall(r"[\w-]+", str(keyword or ""), re.UNICODE)
            if len(token.strip()) >= 3
        ]
        if not query_tokens:
            return results

        filtered: list[Tender] = []
        for tender in results:
            text = self._normalize_search_text(
                " ".join((tender.title or "", tender.description or ""))
            )
            if all(self._token_matches(text, token) for token in query_tokens):
                filtered.append(tender)

        logger.info(
            "B2B-Center: reliable relevance keyword=%r kept=%d excluded=%d",
            keyword, len(filtered), len(results) - len(filtered),
        )
        return filtered

    @staticmethod
    def _normalize_search_text(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "").lower().replace("ё", "е")).strip()

    @staticmethod
    def _normalize_query_token(token: str) -> str:
        return re.sub(r"[^\w-]", "", str(token or "").lower().replace("ё", "е"))

    @staticmethod
    def _token_matches(text: str, token: str) -> bool:
        if not token:
            return True
        if token in text:
            return True
        # Small Russian morphology tolerance: станок/станка/станки/станков,
        # подшипник/подшипники, муфта/муфты, etc.
        stem = token[: max(4, min(len(token), 6))]
        return bool(stem) and re.search(rf"\b{re.escape(stem)}\w*", text)
