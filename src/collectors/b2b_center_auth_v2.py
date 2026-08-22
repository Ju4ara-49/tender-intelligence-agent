"""B2B-Center authentication and search using a persistent Playwright session."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from src.collectors.b2b_center import B2BCenterCollector, BASE_URL, SEARCH_URL
from src.models.tender import Tender

logger = logging.getLogger(__name__)
LOGIN_URL = f"{BASE_URL}/login.html"
SUPPLIER_URL = f"{BASE_URL}/app/next/dashboard/supplier/?group=buy"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_STATE = PROJECT_ROOT / "data" / "b2b_center_storage.json"
load_dotenv(PROJECT_ROOT / ".env")


class AuthenticatedB2BCenterCollector(B2BCenterCollector):
    """B2B-Center collector with persistent authenticated browser search/details."""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.authenticated = False
        self.username = os.getenv("B2B_CENTER_USERNAME", "").strip()
        self.password = os.getenv("B2B_CENTER_PASSWORD", "")
        self.manual_login = os.getenv("B2B_CENTER_MANUAL_LOGIN", "").strip().lower() in {"1", "true", "yes", "on"}
        if not self.username or not self.password:
            logger.warning("B2B-Center: логин/пароль не заданы")
            return
        if STORAGE_STATE.exists():
            self.authenticated = self._use_saved_state()
        if not self.authenticated and self.manual_login:
            self.authenticated = self._manual_login()
        logger.info("B2B-Center: авторизация %s", "выполнена успешно" if self.authenticated else "не подтверждена")

    def _new_context(self, browser, storage=False):
        kwargs = {"user_agent": self.session.headers.get("User-Agent")}
        if storage and STORAGE_STATE.exists():
            kwargs["storage_state"] = str(STORAGE_STATE)
        return browser.new_context(**kwargs)

    def _use_saved_state(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = self._new_context(browser, storage=True)
                page = context.new_page()
                page.goto(SUPPLIER_URL, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                page.wait_for_timeout(2000)
                ok = self._supplier_workspace_available(page)
                cookies = context.cookies() if ok else []
                if ok and cookies:
                    self._copy_cookies(cookies)
                result = ok and bool(cookies) and bool(self.session.cookies)
                browser.close()
                return result
        except Exception:
            logger.exception("B2B-Center: ошибка проверки сохранённой сессии")
            return False

    def _manual_login(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("B2B-Center: требуется Playwright")
            return False
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=False)
                context = self._new_context(browser)
                page = context.new_page()
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                try:
                    username = page.get_by_label("Логин или email", exact=True)
                    password = page.get_by_label("Пароль", exact=True)
                    if username.count() == 0:
                        username = page.locator('input[type="email"], input[name*="login" i], input[type="text"]').first
                    if password.count() == 0:
                        password = page.locator('input[type="password"]').first
                    username.wait_for(state="visible", timeout=10000)
                    password.wait_for(state="visible", timeout=10000)
                    username.fill(self.username)
                    password.fill(self.password)
                    submit = page.get_by_role("button", name="Войти", exact=True).last
                    if submit.count():
                        submit.click()
                except Exception:
                    logger.info("B2B-Center: выполните вход вручную в открывшемся браузере")
                logger.info("B2B-Center: ожидание рабочего места поставщика")
                for _ in range(300):
                    if self._supplier_workspace_available(page):
                        cookies = context.cookies()
                        if cookies:
                            STORAGE_STATE.parent.mkdir(parents=True, exist_ok=True)
                            context.storage_state(path=str(STORAGE_STATE))
                            self._copy_cookies(cookies)
                            browser.close()
                            return bool(self.session.cookies)
                    page.wait_for_timeout(1000)
                browser.close()
                return False
        except Exception:
            logger.exception("B2B-Center: ошибка ручной авторизации")
            return False

    def _authenticated_page_html(self, url: str, wait_selector: str | None = None) -> str:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = self._new_context(browser, storage=True)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
            if wait_selector:
                try:
                    page.locator(wait_selector).first.wait_for(state="attached", timeout=15000)
                except Exception:
                    page.wait_for_timeout(3000)
            else:
                page.wait_for_timeout(2000)
            html = page.content()
            browser.close()
            return html

    def _authenticated_search_html(self, keyword: str) -> str:
        url = f"{SEARCH_URL}?{urlencode({'f_keyword': keyword, 'searching': '1'})}"
        return self._authenticated_page_html(
            url,
            "a.search-results-title[href], a[href*='tender-'], a[href*='tenders-']",
        )

    def _load_search_page(self, keyword: str) -> str:
        if not self.authenticated or not STORAGE_STATE.exists():
            return super()._load_search_page(keyword)
        try:
            return self._authenticated_search_html(keyword)
        except Exception:
            logger.exception("B2B-Center: ошибка браузерного поиска по %s", keyword)
            return ""

    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        """For authenticated B2B pages use the saved browser session."""
        if not self.authenticated or not STORAGE_STATE.exists():
            return super()._get(url, params=params)

        if params:
            query = urlencode(params, doseq=True)
            url = f"{url}{'&' if '?' in url else '?'}{query}"

        try:
            html = self._authenticated_page_html(url)
            response = requests.Response()
            response.status_code = 200
            response.url = url
            response.encoding = "utf-8"
            response._content = html.encode("utf-8")
            return response
        except Exception:
            logger.exception("B2B-Center: ошибка браузерной загрузки %s", url)
            return super()._get(url, params=params)

    def _parse_search_html(self, html: str, keyword: str, since: datetime | None = None) -> list[Tender]:
        """Use the legacy parser when available, then fall back to modern result links."""
        results = super()._parse_search_html(html, keyword, since)
        if results:
            return results

        soup = BeautifulSoup(html or "", "lxml")
        anchors = soup.select("a.search-results-title[href], a[href*='tender-'], a[href*='tenders-']")
        seen: set[str] = set()
        fallback: list[Tender] = []
        for link in anchors:
            href = unescape((link.get("href") or "").strip())
            if not href:
                continue
            url = urljoin(BASE_URL, href)
            external_id = self._extract_external_id(href, link.get_text(" ", strip=True))
            if not external_id or external_id in seen:
                continue
            seen.add(external_id)

            container = link
            for _ in range(5):
                parent = getattr(container, "parent", None)
                if parent is None:
                    break
                container = parent
                if container.name in {"tr", "li", "article"} or "result" in " ".join(container.get("class", [])):
                    break

            row_text = self._clean_text(container.get_text(" ", strip=True))
            title_text = self._clean_text(link.get_text(" ", strip=True))
            desc = link.select_one(".search-results-title-desc")
            if desc is not None:
                title_text = self._clean_text(desc.get_text(" ", strip=True))
            title = self._clean_procedure_title(title_text, external_id)
            if not title:
                title = f"Тендер № {external_id}"

            published = self._parse_date_text(row_text)
            tender = Tender(
                platform=self.platform,
                external_id=str(external_id),
                title=title[:1000],
                url=url,
                description=row_text[:10000],
                price=self._extract_price(row_text),
                currency="RUB",
                published_at=published,
                deadline=None,
                end_date=None,
                customer="",
                region="",
                raw_data={"keyword": keyword, "search_text": row_text[:10000], "search_href": href, "details_url": url},
            )
            if since is not None and published is not None and self._normalize_datetime(published) < self._normalize_datetime(since):
                continue
            self._tender_urls[str(external_id)] = url
            self._tender_titles[str(external_id)] = title
            fallback.append(tender)

        logger.info("B2B-Center: fallback-парсер принял %s результатов", len(fallback))
        return fallback

    @staticmethod
    def _supplier_workspace_available(page) -> bool:
        try:
            if "/app/next/dashboard/supplier/" not in page.url.lower():
                return False
            text = page.locator("body").inner_text(timeout=3000).lower()
            return "рабочее место" in text or "поставщик" in text or "закуп" in text
        except Exception:
            return False

    def _copy_cookies(self, cookies) -> None:
        for cookie in cookies:
            self.session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"), path=cookie.get("path", "/"))
