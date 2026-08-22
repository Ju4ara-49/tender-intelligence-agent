"""B2B-Center authentication using a persistent Playwright session."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from src.collectors.b2b_center import B2BCenterCollector

logger = logging.getLogger(__name__)
BASE_URL = "https://www.b2b-center.ru"
LOGIN_URL = f"{BASE_URL}/login.html"
STORAGE_STATE = Path("data/b2b_center_storage.json")


class AuthenticatedB2BCenterCollector(B2BCenterCollector):
    """B2B-Center collector with persistent browser authentication."""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.authenticated = False
        self.username = os.getenv("B2B_CENTER_USERNAME", "").strip()
        self.password = os.getenv("B2B_CENTER_PASSWORD", "")
        self.manual_login = os.getenv("B2B_CENTER_MANUAL_LOGIN", "").strip().lower() in {"1", "true", "yes", "on"}

        if not self.username or not self.password:
            logger.info("B2B-Center: логин/пароль не заданы; используется открытый доступ")
            return

        if STORAGE_STATE.exists():
            self.authenticated = self._use_saved_state()

        if not self.authenticated and self.manual_login:
            self.authenticated = self._manual_login()
        elif not self.authenticated:
            logger.warning("B2B-Center: сохранённой авторизации нет; для первого входа установите B2B_CENTER_MANUAL_LOGIN=1")

        if self.authenticated:
            logger.info("B2B-Center: авторизация выполнена успешно")
        else:
            logger.warning("B2B-Center: авторизация не выполнена; используется открытый доступ")

    def _use_saved_state(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(storage_state=str(STORAGE_STATE), user_agent=self.session.headers.get("User-Agent"))
                page = context.new_page()
                page.goto(BASE_URL, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                ok = self._page_is_authenticated(page)
                if ok:
                    self._copy_cookies(context)
                browser.close()
                return ok and bool(self.session.cookies)
        except Exception:
            logger.exception("B2B-Center: ошибка проверки сохранённой сессии")
            return False

    def _manual_login(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("B2B-Center: требуется Playwright: pip install -r requirements-b2b-browser.txt")
            return False

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=False)
                context = browser.new_context(user_agent=self.session.headers.get("User-Agent"))
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
                    form = password.locator("xpath=ancestor::form[1]")
                    submit = form.get_by_role("button", name="Войти", exact=True)
                    if submit.count() == 0:
                        submit = page.get_by_role("button", name="Войти", exact=True).last
                    if submit.count():
                        submit.click()
                except Exception:
                    logger.info("B2B-Center: поля входа не заполнены автоматически; выполните вход вручную")

                logger.info("B2B-Center: выполните вход в открывшемся окне браузера; состояние будет сохранено автоматически")
                for _ in range(180):
                    if self._page_is_authenticated(page):
                        cookies = context.cookies()
                        if cookies:
                            context.storage_state(path=str(STORAGE_STATE))
                            self._copy_cookies(context)
                            browser.close()
                            logger.info("B2B-Center: ручная авторизация сохранена; cookies=%d", len(cookies))
                            return True
                    page.wait_for_timeout(1000)

                logger.warning("B2B-Center: ручная авторизация не завершена за 180 секунд")
                browser.close()
                return False
        except Exception:
            logger.exception("B2B-Center: ошибка ручной авторизации")
            return False

    @staticmethod
    def _page_is_authenticated(page) -> bool:
        try:
            url = page.url.lower()
            text = page.locator("body").inner_text(timeout=3000).lower()
        except Exception:
            return False
        bad = ("неверный пароль", "неверный логин", "неверные учетные данные", "ошибка авторизации", "не удалось войти")
        if any(x in text for x in bad):
            return False
        good = ("личный кабинет", "выйти", "logout", "личные данные", "мой профиль")
        return any(x in text for x in good) or "/login.html" not in url

    def _copy_cookies(self, context) -> None:
        for cookie in context.cookies():
            self.session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"), path=cookie.get("path", "/"))
