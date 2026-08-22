"""Browser-based public collectors for JS-heavy tender platforms.

The platforms expose their search UI through client-side JavaScript, so a
normal requests parser is unreliable. These collectors use Playwright with
short, bounded waits and conservative link parsing. They never bypass login,
CAPTCHA, or access controls.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from src.collectors.base import BaseCollector
from src.models.tender import Tender

logger = logging.getLogger(__name__)


class _BrowserTenderCollector(BaseCollector):
    BASE_URL = ""
    SEARCH_HINTS: tuple[str, ...] = ()
    LINK_HINTS: tuple[str, ...] = ("procedure", "tender", "zakup", "purchase")

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        self.timeout_ms = int(self.config.get("timeout_seconds", 30)) * 1000
        self.max_results = int(self.config.get("max_results", 100))
        self._urls: dict[str, str] = {}

    def is_enabled(self, config: dict) -> bool:
        return bool(config.get("collectors", {}).get(self.platform, {}).get("enabled", True))

    def search(self, keywords: list[str], since: datetime | None = None) -> list[Tender]:
        terms = [str(x).strip() for x in keywords if str(x).strip()]
        if not terms:
            return []
        query = " ".join(terms)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(locale="ru-RU")
                page.goto(self.BASE_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
                self._perform_search(page, query)
                page.wait_for_timeout(1200)
                html = page.content()
                browser.close()
        except PlaywrightTimeoutError as exc:
            logger.warning("%s: timeout: %s", self.platform, exc)
            return []
        except Exception as exc:
            logger.warning("%s: browser search failed: %s", self.platform, exc)
            return []
        results = self._parse_results(html)
        logger.info("%s: найдено %d процедур", self.platform, len(results))
        return results[: self.max_results]

    def get_details(self, external_id: str) -> Tender | None:
        url = self._urls.get(str(external_id))
        if not url:
            return None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(locale="ru-RU")
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(500)
                tender = self._parse_detail(page.content(), str(external_id), url)
                browser.close()
                return tender
        except Exception as exc:
            logger.warning("%s: detail failed %s: %s", self.platform, external_id, exc)
            return None

    def _perform_search(self, page, query: str) -> None:
        selectors = [
            "input[type='search']",
            "input[name*='search' i]",
            "input[name*='query' i]",
            "input[placeholder*='поиск' i]",
            "input[placeholder*='закуп' i]",
            "input[placeholder*='наимен' i]",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() and locator.is_visible():
                    locator.fill(query)
                    locator.press("Enter")
                    return
            except Exception:
                continue
        # Some SPAs expose search through a visible button first.
        for text in self.SEARCH_HINTS:
            try:
                button = page.get_by_text(text, exact=False).first
                if button.count() and button.is_visible():
                    button.click()
                    page.wait_for_timeout(500)
                    break
            except Exception:
                continue
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() and locator.is_visible():
                    locator.fill(query)
                    locator.press("Enter")
                    return
            except Exception:
                continue

    def _parse_results(self, html: str) -> list[Tender]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[Tender] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(self.BASE_URL, str(anchor.get("href", "")).strip())
            title = " ".join(anchor.stripped_strings)
            if not title or len(title) < 5:
                continue
            low = href.lower()
            if not any(hint in low for hint in self.LINK_HINTS):
                continue
            external_id = self._extract_id(href, title)
            if not external_id or external_id in seen:
                continue
            seen.add(external_id)
            self._urls[external_id] = href
            results.append(Tender(platform=self.platform, external_id=external_id, title=title[:1000], url=href, description=title, raw_data={"source": self.BASE_URL}))
        return results

    def _parse_detail(self, html: str, external_id: str, url: str) -> Tender:
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.find("h1") or soup.find("title")
        title = " ".join(title_node.stripped_strings) if title_node else f"Процедура {external_id}"
        text = " ".join(soup.stripped_strings)
        price = self._extract_price(text)
        deadline = self._extract_date(text)
        return Tender(platform=self.platform, external_id=external_id, title=title[:1000], url=url, description=text[:10000], price=price, deadline=deadline, raw_data={"source": url})

    @staticmethod
    def _extract_id(href: str, title: str) -> str | None:
        patterns = [r"(?:procedure|tender|purchase)[^0-9]{0,20}(\d{5,})", r"(?:/|#)(\d{6,})(?:/|$)", r"\b(\d{7,})\b"]
        for source in (href, title):
            for pattern in patterns:
                match = re.search(pattern, source, re.I)
                if match:
                    return match.group(1)
        return None

    @staticmethod
    def _extract_price(text: str) -> float | None:
        for match in re.finditer(r"(?:цена|стоимость|НМЦ|начальн\w* цена)[^0-9]{0,40}([0-9][0-9\s]{2,}(?:[.,][0-9]{1,2})?)", text, re.I):
            try:
                return float(match.group(1).replace(" ", "").replace(",", "."))
            except ValueError:
                continue
        return None

    @staticmethod
    def _extract_date(text: str) -> datetime | None:
        match = re.search(r"(?:до|окончани\w*|срок[^0-9]{0,10})[^0-9]{0,30}(\d{1,2})[./](\d{1,2})[./](20\d{2})", text, re.I)
        if not match:
            return None
        try:
            return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            return None


class RtsTenderCollector(_BrowserTenderCollector):
    platform = "rts_tender"
    BASE_URL = "https://www.rts-tender.ru/"
    SEARCH_HINTS = ("Поиск", "Поиск закупок", "Закупки")


class TmkCollector(_BrowserTenderCollector):
    platform = "tmk"
    BASE_URL = "https://zakupki.tmk-group.com/"
    SEARCH_HINTS = ("Поиск", "Закупки", "Найти")
    LINK_HINTS = ("procedure", "tender", "com/", "zakup")
