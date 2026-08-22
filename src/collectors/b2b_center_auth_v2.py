"""B2B-Center authentication and search using a persistent Playwright session."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from src.collectors.b2b_center import B2BCenterCollector

logger = logging.getLogger(__name__)
BASE_URL = "https://www.b2b-center.ru"
LOGIN_URL = f"{BASE_URL}/login.html"
SUPPLIER_URL = f"{BASE_URL}/app/next/dashboard/supplier/?group=buy"
SEARCH_URL = f"{BASE_URL}/market/"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_STATE = PROJECT_ROOT / "data" / "b2b_center_storage.json"
load_dotenv(PROJECT_ROOT / ".env")


class AuthenticatedB2BCenterCollector(B2BCenterCollector):
    """B2B-Center collector with persistent authenticated browser search."""

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
                    self._copy_cookies(context)
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
                            self._copy_cookies(context)
                            browser.close()
                            return bool(self.session.cookies)
                    page.wait_for_timeout(1000)
                browser.close()
                return False
        except Exception:
            logger.exception("B2B-Center: ошибка ручной авторизации")
            return False

    def _authenticated_search_html(self, keyword: str) -> str:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = self._new_context(browser, storage=True)
            page = context.new_page()
            url = f"{SEARCH_URL}?{urlencode({'f_keyword': keyword, 'searching': '1'})}"
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
            try:
                page.locator("a.search-results-title[href]").first.wait_for(state="attached", timeout=15000)
            except Exception:
                page.wait_for_timeout(5000)
            html = page.content()
            browser.close()
            return html

    def _load_search_page(self, keyword: str) -> str:
        if not self.authenticated or not STORAGE_STATE.exists():
            return super()._load_search_page(keyword)
        try:
            html = self._authenticated_search_html(keyword)
            soup = BeautifulSoup(html, "lxml")
            if soup.select_one("table.search-results") is None:
                link = soup.select_one("a.search-results-title[href]")
                if link is not None:
                    table = link.find_parent("table")
                    if table is not None:
                        classes = table.get("class", [])
                        if "search-results" not in classes:
                            classes.append("search-results")
                            table["class"] = classes
                        html = str(soup)
            return html
        except Exception:
            logger.exception("B2B-Center: ошибка браузерного поиска по %s", keyword)
            return ""

    @staticmethod
    def _supplier_workspace_available(page) -> bool:
        try:
            if "/app/next/dashboard/supplier/" not in page.url.lower():
                return False
            text = page.locator("body").inner_text(timeout=3000).lower()
            return "рабочее место" in text or "поставщик" in text or "закуп" in text
        except Exception:
            return False

    def _copy_cookies(self, context) -> None:
        for cookie in context.cookies():
            self.session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"), path=cookie.get("path", "/"))
