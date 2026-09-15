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
                if since is not None and tender.published_at is not None:
                    published = tender.published_at
                    if published.tzinfo is None:
                        published = published.astimezone()
                    if published < since:
                        continue
                merged[tender.unique_key] = tender
                if len(merged) >= self.max_results:
                    break
            if len(merged) >= self.max_results:
                break
        logger.info("%s: найдено %d уникальных процедур", self.platform, len(merged))
        return list(merged.values())[: self.max_results]

    @staticmethod
    def _wait_for_initial_dom(page) -> None:
        """Wait for the DOM without requiring all SPA resources to finish loading."""
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        try:
            page.locator("body").wait_for(state="attached", timeout=5000)
        except Exception:
            pass

    def _goto(self, page, url: str) -> None:
        """Navigate to a JS-heavy portal without blocking on long-lived requests."""
        page.goto(url, wait_until="commit", timeout=self.timeout_ms)
        self._wait_for_initial_dom(page)

    def _search_one(self, query: str) -> list[Tender]:
        logger.info("%s: поиск по ключевому слову: %s", self.platform, query)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(locale="ru-RU")
                self._goto(page, self.BASE_URL)
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

        parsed_results = self._parse_results(html)
        results = [tender for tender in parsed_results if self._tender_matches_query(tender, query)]
        if parsed_results and not results:
            logger.warning(
                "%s: RESULT_QUERY_MISMATCH — parser returned %d procedures but none contain query %r; rejecting unverified results",
                self.platform, len(parsed_results), query,
            )
        logger.info(
            "%s: keyword=%r: parsed=%d, matched=%d",
            self.platform, query, len(parsed_results), len(results),
        )
        return results

    @classmethod
    def _tender_matches_query(cls, tender: Tender, query: str) -> bool:
        normalized_query = cls._normalize_search_text(query)
        if not normalized_query:
            return False
        haystack = cls._normalize_search_text(
            " ".join((tender.title or "", tender.description or "", str((tender.raw_data or {}).get("subject") or "")))
        )
        if normalized_query in haystack:
            return True
        variants = {
            "станок": ("станок", "станка", "станки", "станков", "станкам", "станками", "станке", "станком"),
            "редуктор": ("редуктор", "редуктора", "редукторы", "редукторов", "редукторам", "редукторами", "редукторе", "редуктором"),
        }
        return any(item in haystack for item in variants.get(normalized_query, ()))

    @staticmethod
    def _normalize_search_text(value: str) -> str:
        return re.sub(r"[^0-9a-zа-яё]+", " ", str(value or "").casefold()).strip()

    def get_details(self, external_id: str) -> Tender | None:
        url = self._urls.get(str(external_id))
        if not url:
            return None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(locale="ru-RU")
                self._goto(page, url)
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
            "input[placeholder*='предмет' i]", "input[aria-label*='поиск' i]",
            "input[aria-label*='закуп' i]", "input[aria-label*='найти' i]",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() and locator.is_visible():
                    locator.fill(query)
                    locator.press("Enter")
                    logger.info("%s: SEARCH_SUBMITTED selector=%s", self.platform, selector)
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
                    logger.info("%s: SEARCH_SUBMITTED selector=%s", self.platform, selector)
                    return
            except Exception:
                continue
        logger.warning("%s: поле поиска не найдено для запроса %r", self.platform, query)

    def _parse_results(self, html: str) -> list[Tender]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[Tender] = []
        seen: set[str] = set()
        base_host = urlparse(self.BASE_URL).netloc.lower()

        candidates: list[tuple[object, str]] = []
        nav_attrs = ("href", "data-href", "data-url", "data-link", "routerlink", "data-routerlink")
        onclick_re = re.compile(
            r"(?:location(?:\.href)?\s*=|window\.location(?:\.href)?\s*=|window\.open\s*\()\s*['\"]([^'\"]+)['\"]",
            re.I,
        )
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
        published_at = self._extract_datetime(text, ("Дата публикации", "Дата размещения", "Опубликовано", "Размещено"))
        start_date = self._extract_datetime(text, ("Дата начала", "Начало приема", "Начало подачи"))
        end_date = deadline or self._extract_datetime(text, ("Дата окончания", "Окончание приема", "Окончание подачи"))
        customer = self._extract_labeled_value(text, ("Заказчик", "Организатор", "Организация-заказчик"))
        region = self._extract_labeled_value(text, ("Регион поставки", "Место поставки", "Место выполнения", "Регион"))
        law_type = self._extract_labeled_value(text, ("Закон", "Вид закона", "Федеральный закон", "Тип закупки"))
        advance_percent = self._extract_percent(text, ("Аванс", "Предоплата", "Размер аванса"))
        postpayment_days = self._extract_days(text, ("Отсрочка платежа", "Срок оплаты", "Условия оплаты", "Постоплата"))
        application_security = self._extract_percent(text, ("Обеспечение заявки", "Обеспечение предложения"))
        contract_security = self._extract_percent(text, ("Обеспечение исполнения", "Обеспечение контракта", "Обеспечение договора"))

        raw_data = {
            "source": url,
            "published_at": published_at.isoformat() if published_at else None,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        }
        if advance_percent is not None:
            raw_data["advance_payment"] = {"percent": advance_percent}
        if postpayment_days is not None:
            raw_data["postpayment"] = {"days": postpayment_days}
        if application_security is not None:
            raw_data["application_security"] = {"percent": application_security}
        if contract_security is not None:
            raw_data["contract_security"] = {"percent": contract_security}

        return Tender(
            platform=self.platform,
            external_id=external_id,
            title=title[:1000],
            url=url,
            description=text[:10000],
            price=price,
            deadline=end_date,
            published_at=published_at,
            start_date=start_date,
            end_date=end_date,
            region=region,
            customer=customer,
            law_type=law_type,
            advance_required=advance_percent is not None and advance_percent > 0,
            advance_percent=advance_percent,
            postpayment_days=postpayment_days,
            application_security_percent=application_security,
            contract_security_percent=contract_security,
            raw_data=raw_data,
        )

    @staticmethod
    def _extract_labeled_value(text: str, labels: tuple[str, ...]) -> str:
        label_pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(rf"(?:{label_pattern})\s*[:\-]?\s*(.+?)(?=\s+(?:Заказчик|Организатор|Регион|Место|Дата|Срок|Цена|НМЦ|Обеспечение|Аванс|Оплата)\b|$)", text, re.I)
        return match.group(1).strip(" ;,\t")[:1000] if match else ""

    @staticmethod
    def _extract_percent(text: str, labels: tuple[str, ...]) -> float | None:
        label_pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(rf"(?:{label_pattern})[^%\d]{{0,60}}(\d+(?:[.,]\d+)?)\s*%", text, re.I)
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            return None

    @staticmethod
    def _extract_days(text: str, labels: tuple[str, ...]) -> int | None:
        label_pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(rf"(?:{label_pattern})[^\d]{{0,60}}(\d{{1,4}})\s*(?:дн\w*|сут\w*)", text, re.I)
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _extract_datetime(text: str, labels: tuple[str, ...]) -> datetime | None:
        label_pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(rf"(?:{label_pattern})[^0-9]{{0,60}}(\d{{1,2}})[./](\d{{1,2}})[./](20\d{{2}})(?:[^0-9]{{0,20}}(\d{{1,2}}):([0-9]{{2}}))?", text, re.I)
        if not match:
            return None
        try:
            return datetime(
                int(match.group(3)), int(match.group(2)), int(match.group(1)),
                int(match.group(4) or 0), int(match.group(5) or 0),
            )
        except ValueError:
            return None

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
    BASE_URL = "https://www.rts-tender.ru/"
    SEARCH_HINTS = ("Поиск", "Поиск закупок", "Закупки")
    LINK_HINTS = ("/poisk/", "/procedure", "/tender", "zakup")


class TmkCollector(_BrowserTenderCollector):
    platform = "tmk"
    BASE_URL = "https://zakupki.tmk-group.com/#tmk/front/index"
    SEARCH_HINTS = ("Поиск", "Закупки", "Найти")
    LINK_HINTS = ("tmk/front", "procedure", "tender", "zakup")
