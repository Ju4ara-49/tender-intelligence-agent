"""Browser-based public collectors for JS-heavy tender platforms.

The platforms expose their search UI through client-side JavaScript, so a
normal requests parser is unreliable. These collectors use Playwright with
bounded waits and conservative link parsing. They never bypass login,
CAPTCHA, WAF, or access controls.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

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
        merged: dict[str, Tender] = {}
        for term in terms:
            results = self._search_one(term)
            for tender in results:
                merged[tender.unique_key] = tender
                if len(merged) >= self.max_results:
                    break
            if len(merged) >= self.max_results:
                break
        logger.info("%s: найдено %d уникальных процедур", self.platform, len(merged))
        return list(merged.values())[: self.max_results]

    def _search_one(self, query: str) -> list[Tender]:
        logger.info("%s: поиск по ключевому слову: %s", self.platform, query)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(locale="ru-RU")
                page.goto(self.BASE_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(1800)
                self._perform_search(page, query)
                page.wait_for_timeout(3000)
                try:
                    page.wait_for_load_state("networkidle", timeout=7000)
                except Exception:
                    pass
                html = self._collect_rendered_html(page)
                browser.close()
        except PlaywrightTimeoutError as exc:
            logger.warning("%s: timeout for %r: %s", self.platform, query, exc)
            return []
        except Exception as exc:
            logger.warning("%s: browser search failed for %r: %s", self.platform, query, exc)
            return []

        soup_text = " ".join(BeautifulSoup(html, "html.parser").stripped_strings).lower()
        if "web application firewall" in soup_text or "временно заблокирован" in soup_text:
            logger.warning("%s: портал вернул страницу WAF; поиск невозможен без обхода защиты", self.platform)
            return []

        results = self._parse_results(html)
        logger.info("%s: keyword=%r: принято %d результатов", self.platform, query, len(results))
        return results

    def get_details(self, external_id: str) -> Tender | None:
        url = self._urls.get(str(external_id))
        if not url:
            return None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(locale="ru-RU")
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(2500)
                self._open_information_sections(page)
                page.wait_for_timeout(1200)
                try:
                    page.wait_for_load_state("networkidle", timeout=7000)
                except Exception:
                    pass
                html = self._collect_rendered_html(page)
                browser.close()
                soup_text = " ".join(BeautifulSoup(html, "html.parser").stripped_strings).lower()
                if "web application firewall" in soup_text or "временно заблокирован" in soup_text:
                    logger.warning("%s: WAF при загрузке деталей %s", self.platform, external_id)
                    return None
                return self._parse_detail(html, str(external_id), url)
        except Exception as exc:
            logger.warning("%s: detail failed %s: %s", self.platform, external_id, exc)
            return None

    @staticmethod
    def _collect_rendered_html(page) -> str:
        chunks: list[str] = []
        try:
            chunks.append(page.content())
        except Exception:
            pass
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                frame_html = frame.content()
                if frame_html:
                    chunks.append(frame_html)
            except Exception:
                continue
        return "\n".join(chunks)

    @staticmethod
    def _open_information_sections(page) -> None:
        labels = (
            "Общая информация", "Сведения о закупке", "Информация о закупке",
            "Основная информация", "Сведения", "Условия закупки",
        )
        for label in labels:
            try:
                loc = page.get_by_text(label, exact=False)
                count = min(loc.count(), 3)
                for idx in range(count):
                    item = loc.nth(idx)
                    if item.is_visible():
                        item.click(timeout=1000)
                        page.wait_for_timeout(250)
            except Exception:
                continue

    def _perform_search(self, page, query: str) -> None:
        selectors = [
            "input[type='search']", "input[name*='search' i]", "input[name*='query' i]",
            "input[placeholder*='поиск' i]", "input[placeholder*='закуп' i]",
            "input[placeholder*='наимен' i]", "input[placeholder*='ключев' i]",
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
        for text in self.SEARCH_HINTS:
            try:
                button = page.get_by_text(text, exact=False).first
                if button.count() and button.is_visible():
                    button.click()
                    page.wait_for_timeout(700)
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
        logger.warning("%s: поле поиска не найдено для запроса %r", self.platform, query)

    def _parse_results(self, html: str) -> list[Tender]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[Tender] = []
        seen: set[str] = set()
        base_host = urlparse(self.BASE_URL).netloc.lower()

        # SPA portals do not consistently expose result navigation as <a href>.
        # Collect all common navigation attributes, including onclick URLs.
        candidates: list[tuple[object, str]] = []
        nav_attrs = ("href", "data-href", "data-url", "data-link", "routerlink", "data-routerlink")
        onclick_re = re.compile(r"(?:location(?:\.href)?|window\.open)\s*\(?\s*['\"]([^'\"]+)['\"]", re.I)
        for node in soup.find_all(True):
            raw = None
            for attr in nav_attrs:
                value = node.get(attr)
                if value:
                    raw = str(value).strip()
                    break
            if not raw:
                onclick = str(node.get("onclick", ""))
                match = onclick_re.search(onclick)
                if match:
                    raw = match.group(1).strip()
            if raw and not raw.lower().startswith(("javascript:", "#")):
                candidates.append((node, raw))

        for node, raw_href in candidates:
            href = urljoin(self.BASE_URL, raw_href)
            parsed = urlparse(href)
            if parsed.netloc and parsed.netloc.lower() != base_host:
                continue

            # A result card may keep the actual text on its parent while the
            # navigation attribute is on a tiny icon/button. Prefer a useful
            # nearby card label over an icon's empty/one-word text.
            title = " ".join(node.stripped_strings)
            if len(title) < 5 and node.parent is not None:
                parent_title = " ".join(node.parent.stripped_strings)
                if len(parent_title) > len(title):
                    title = parent_title
            if not title or len(title) < 5:
                continue

            low = href.lower()
            if not any(hint in low for hint in self.LINK_HINTS) and not re.search(r"\d{6,}", href + " " + title):
                continue

            external_id = self._extract_id(href, title)
            if not external_id or external_id in seen:
                continue
            seen.add(external_id)
            self._urls[external_id] = href
            results.append(Tender(
                platform=self.platform,
                external_id=external_id,
                title=title[:1000],
                url=href,
                description=title,
                raw_data={"source": self.BASE_URL},
            ))
        return results

    def _parse_detail(self, html: str, external_id: str, url: str) -> Tender:
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.find("h1") or soup.find("title")
        title = " ".join(title_node.stripped_strings) if title_node else f"Процедура {external_id}"
        text = " ".join(soup.stripped_strings)
        price = self._extract_price(text)
        deadline = self._extract_date(text)
        return Tender(platform=self.platform, external_id=external_id, title=title[:1000], url=url,
                      description=text[:10000], price=price, deadline=deadline,
                      raw_data={"source": url})

    @staticmethod
    def _extract_id(href: str, title: str) -> str | None:
        patterns = [
            r"(?:procedure|tender|purchase)[^0-9]{0,30}(\d{5,})",
            r"(?:/|#)l(\d{6,})(?:[-/]|$)",
            r"(?:/|#)(\d{6,})(?:/|$)",
            r"\b(\d{7,})\b",
        ]
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
    BASE_URL = "https://www.rts-tender.ru/poisk/"
    SEARCH_HINTS = ("Поиск", "Поиск закупок", "Закупки")
    LINK_HINTS = ("/poisk/id/", "/poisk/search", "procedure", "tender")


class TmkCollector(_BrowserTenderCollector):
    platform = "tmk"
    BASE_URL = "https://zakupki.tmk-group.com/#tmk/front/index"
    SEARCH_HINTS = ("Поиск", "Закупки", "Найти")
    LINK_HINTS = ("tmk/front", "procedure", "tender", "zakup")
