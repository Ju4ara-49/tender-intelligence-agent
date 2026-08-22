"""Modern B2B-Center collector for /app/next/market-search."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from html import unescape
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from src.collectors.b2b_center_auth_v2 import AuthenticatedB2BCenterCollector, STORAGE_STATE
from src.models.tender import Tender

logger = logging.getLogger(__name__)

BASE_URL = "https://www.b2b-center.ru"
MODERN_SEARCH_URL = f"{BASE_URL}/app/next/market-search"


class ModernB2BCenterCollector(AuthenticatedB2BCenterCollector):
    """Use B2B-Center's current market-search UI instead of legacy /market/."""

    platform = "b2b_center"

    def _modern_search_url(self, keyword: str) -> str:
        return (
            f"{MODERN_SEARCH_URL}?q={quote_plus(keyword)}"
            "&company_type=2&include_firm_tree=false&sort=date_desc"
            "&trade=buy&show=actual"
        )

    def _authenticated_search_html(self, keyword: str) -> str:
        return self._authenticated_page_html(self._modern_search_url(keyword))

    def _load_search_page(self, keyword: str) -> str:
        """Load the current /app/next/market-search page in a browser."""
        try:
            if self.authenticated and STORAGE_STATE.exists():
                return self._authenticated_search_html(keyword)
        except Exception:
            logger.exception("B2B-Center: authenticated modern search failed: %s", keyword)

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(locale="ru-RU", user_agent=self.session.headers.get("User-Agent"))
                page.goto(self._modern_search_url(keyword), wait_until="domcontentloaded", timeout=self.timeout * 1000)
                page.wait_for_timeout(3500)
                try:
                    page.wait_for_load_state("networkidle", timeout=7000)
                except Exception:
                    pass
                html = page.content()
                browser.close()
                return html
        except Exception:
            logger.exception("B2B-Center: modern browser search failed: %s", keyword)
            return ""

    def _parse_search_html(self, html: str, keyword: str, since: datetime | None = None) -> list[Tender]:
        """Parse current React/Next result cards without legacy table markup."""
        soup = BeautifulSoup(html or "", "html.parser")
        results: list[Tender] = []
        seen: set[str] = set()
        max_results = int(self.config.get("max_results", max(self.max_pages * 20, 100)))

        for link in soup.find_all("a", href=True):
            href = unescape(str(link.get("href", "")).strip())
            if not href:
                continue
            url = urljoin(BASE_URL, href)
            if "b2b-center.ru" not in url.lower():
                continue
            external_id = self._extract_modern_id(href, link.get_text(" ", strip=True))
            if not external_id or external_id in seen or not self._looks_like_procedure_url(href):
                continue

            container = self._result_container(link)
            row_text = self._clean_text(container.get_text(" ", strip=True))
            title = self._extract_modern_title(link, container, external_id)
            if not title:
                continue

            published = self._extract_date_from_text(row_text, published=True)
            deadline = self._extract_date_from_text(row_text, published=False)
            price = self._extract_price(row_text)
            if since is not None and published is not None and self._normalize_datetime(published) < self._normalize_datetime(since):
                continue

            seen.add(external_id)
            tender = Tender(
                platform=self.platform,
                external_id=external_id,
                title=title[:1000],
                url=url,
                description=row_text[:10000],
                price=price,
                currency="RUB",
                published_at=published,
                deadline=deadline,
                end_date=deadline,
                customer=self._extract_labeled_value(row_text, ("Заказчик", "Организатор"))[:1000],
                region=self._extract_region(row_text),
                raw_data={
                    "keyword": keyword,
                    "search_text": row_text[:10000],
                    "search_href": href,
                    "details_url": url,
                    "search_source": MODERN_SEARCH_URL,
                },
            )
            self._tender_urls[external_id] = url
            self._tender_titles[external_id] = title
            results.append(tender)
            if len(results) >= max_results:
                break

        logger.info("B2B-Center: modern search keyword=%r: принято %d результатов", keyword, len(results))
        return results

    @staticmethod
    def _looks_like_procedure_url(href: str) -> bool:
        low = href.lower()
        return any(x in low for x in ("tender", "procedure", "purchase", "trade")) or bool(re.search(r"\d{7,}", href))

    @staticmethod
    def _extract_modern_id(href: str, text: str) -> str | None:
        patterns = (
            r"(?:tender|procedure|purchase|trade)[^0-9]{0,40}(\d{6,})",
            r"(?:/|#)(\d{7,})(?:/|[?#]|$)",
            r"\b(\d{9,})\b",
        )
        for source in (href, text):
            for pattern in patterns:
                match = re.search(pattern, source, re.I)
                if match:
                    return match.group(1)
        return None

    @staticmethod
    def _result_container(link):
        node = link
        for _ in range(8):
            parent = getattr(node, "parent", None)
            if parent is None:
                break
            node = parent
            classes = " ".join(node.get("class", [])) if hasattr(node, "get") else ""
            role = node.get("role", "") if hasattr(node, "get") else ""
            if node.name in {"article", "li", "tr"} or role in {"article", "listitem"} or any(k in classes.lower() for k in ("card", "result", "item", "trade")):
                break
        return node

    def _extract_modern_title(self, link, container, external_id: str) -> str:
        for selector in ("h1", "h2", "h3", "h4", "[data-testid*='title' i]", "[class*='title' i]"):
            node = container.select_one(selector)
            if node is not None:
                text = self._clean_text(node.get_text(" ", strip=True))
                if len(text) >= 5 and not re.fullmatch(r"\d{6,}", text):
                    return self._clean_procedure_title(text, external_id)
        text = self._clean_text(link.get_text(" ", strip=True))
        return self._clean_procedure_title(text, external_id) if text else ""

    @classmethod
    def _extract_date_from_text(cls, text: str, published: bool) -> datetime | None:
        labels = ("опублик", "размещ", "дата публикации", "начало") if published else ("окончание", "срок", "прием заявок", "подачи заявок", "до")
        pattern = r"(?:" + "|".join(labels) + r")[^0-9]{0,80}(\d{1,2}[./-]\d{1,2}[./-]20\d{2}(?:\s+\d{1,2}:\d{2})?)"
        match = re.search(pattern, text, re.I)
        return cls._parse_date_text(match.group(1)) if match else None

    @staticmethod
    def _extract_labeled_value(text: str, labels: tuple[str, ...]) -> str:
        for label in labels:
            match = re.search(re.escape(label) + r"\s*[:\-]?\s*([^|;]{3,250})", text, re.I)
            if match:
                return match.group(1).strip()
        return ""
