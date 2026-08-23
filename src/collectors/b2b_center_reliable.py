"""Reliable public B2B-Center discovery adapter.

The current B2B-Center site still exposes a stable public /market/ search
with f_keyword/searching parameters and offset pagination. This adapter keeps
that discovery path independent from the JS-heavy modern UI. Details continue
to use the authenticated modern collector.
"""
from __future__ import annotations

import logging
import re
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
        max_pages = max(1, min(int(self.config.get("max_pages", 10)), 50))
        page_size = max(1, int(self.config.get("page_size", 20)))
        chunks: list[str] = []
        total_links = 0

        for page_no in range(max_pages):
            offset = page_no * page_size
            try:
                response = self._get(
                    LEGACY_SEARCH_URL,
                    params={
                        "f_keyword": keyword,
                        "searching": "1",
                        "from": str(offset),
                    },
                )
                html = response.text or ""
                if not html:
                    break
                chunks.append(html)

                soup = BeautifulSoup(html, "html.parser")
                links = soup.select("a[href*='/tender-']")
                total_links += len(links)
                logger.info(
                    "B2B-Center: reliable search keyword=%r page=%d offset=%d links=%d",
                    keyword, page_no + 1, offset, len(links),
                )

                if not links:
                    break
                if page_no > 0 and len(links) < page_size:
                    break
            except Exception:
                logger.exception(
                    "B2B-Center: reliable search page failed keyword=%r page=%d",
                    keyword, page_no + 1,
                )
                break

            delay = float(self.config.get("request_delay_seconds", 0.5))
            if delay > 0:
                import time
                time.sleep(delay)

        logger.info(
            "B2B-Center: reliable search keyword=%r pages=%d procedure_links=%d",
            keyword, len(chunks), total_links,
        )
        return "\n".join(chunks)

    def _parse_search_html(
        self,
        html: str,
        keyword: str,
        since: datetime | None = None,
    ) -> list[Tender]:
        # Use the proven modern parser for normalization, but apply an
        # explicit relevance gate because B2B-Center may return broad/default
        # rows when a query parameter is ignored or partially applied.
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
