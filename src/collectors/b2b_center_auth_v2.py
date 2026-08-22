"""B2B-Center authentication using the real JavaScript login page."""

from __future__ import annotations

import logging
import os

from src.collectors.b2b_center import B2BCenterCollector


logger = logging.getLogger(__name__)
BASE_URL = "https://www.b2b-center.ru"
LOGIN_URL = f"{BASE_URL}/members/login.html"


class AuthenticatedB2BCenterCollector(B2BCenterCollector):
    """B2B-Center collector with browser-based login fallback.

    Credentials are read only from local environment variables.
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.authenticated = False
        self.username = os.getenv("B2B_CENTER_USERNAME", "").strip()
        self.password = os.getenv("B2B_CENTER_PASSWORD", "")

        if not self.username or not self.password:
            logger.info(
                "B2B-Center: логин/пароль не заданы; используется открытый доступ"
            )
            return

        self.authenticated = self._login_with_browser()
        if self.authenticated:
            logger.info("B2B-Center: авторизация выполнена успешно")
        else:
            logger.warning(
                "B2B-Center: авторизация не выполнена; используется открытый доступ"
            )

    def _login_with_browser(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error(
                "B2B-Center: для авторизации требуется Playwright. "
                "Установите зависимости командой: "
                "pip install -r requirements-b2b-browser.txt"
            )
            return False

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=self.session.headers.get("User-Agent")
                )
                page = context.new_page()
                page.goto(
                    LOGIN_URL,
                    wait_until="domcontentloaded",
                    timeout=self.timeout * 1000,
                )

                password_field = page.locator('input[type="password"]').first
                password_field.wait_for(timeout=self.timeout * 1000)

                form = password_field.locator("xpath=ancestor::form[1]")
                username_field = form.locator(
                    'input[type="text"], input[type="email"]'
                ).first
                if username_field.count() == 0:
                    username_field = page.locator(
                        'input[type="text"], input[type="email"]'
                    ).first

                username_field.fill(self.username)
                password_field.fill(self.password)

                buttons = form.locator('button, input[type="submit"]')
                button = buttons.first
                if button.count() == 0:
                    button = page.get_by_text("Войти", exact=True).first
                button.click()

                page.wait_for_timeout(2000)
                text = page.locator("body").inner_text(timeout=5000).lower()

                bad = (
                    "неверный пароль",
                    "неверный логин",
                    "ошибка авторизации",
                )
                good = (
                    "личный кабинет",
                    "выйти",
                    "logout",
                    "личные данные",
                )
                authenticated = any(x in text for x in good) and not any(
                    x in text for x in bad
                )

                if authenticated:
                    for cookie in context.cookies():
                        self.session.cookies.set(
                            cookie["name"],
                            cookie["value"],
                            domain=cookie.get("domain"),
                            path=cookie.get("path", "/"),
                        )

                browser.close()
                return authenticated
        except Exception:
            logger.exception("B2B-Center: ошибка браузерной авторизации")
            return False
