"""B2B-Center authentication using the current JavaScript login page."""

from __future__ import annotations

import logging
import os

from src.collectors.b2b_center import B2BCenterCollector


logger = logging.getLogger(__name__)
BASE_URL = "https://www.b2b-center.ru"
LOGIN_URL = f"{BASE_URL}/login.html"


class AuthenticatedB2BCenterCollector(B2BCenterCollector):
    """B2B-Center collector with browser-based login.

    Credentials are read only from local environment variables. The browser is
    used only for the login flow; cookies are copied into the existing
    requests session and the normal collector then reuses that session.
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

                # Current B2B-Center login page exposes fields by their labels:
                # "Логин или email" and "Пароль". Prefer label-based selectors
                # and keep generic fallbacks for minor markup changes.
                username_field = page.get_by_label("Логин или email", exact=True)
                password_field = page.get_by_label("Пароль", exact=True)

                if username_field.count() == 0:
                    username_field = page.locator(
                        'input[name*="login" i], input[name*="email" i], '
                        'input[type="email"], input[type="text"]'
                    ).first
                if password_field.count() == 0:
                    password_field = page.locator('input[type="password"]').first

                username_field.wait_for(state="visible", timeout=self.timeout * 1000)
                password_field.wait_for(state="visible", timeout=self.timeout * 1000)

                username_field.fill(self.username)
                password_field.fill(self.password)

                # Submit the login form. If the button is rendered outside the
                # form, use the visible text fallback.
                form = password_field.locator("xpath=ancestor::form[1]")
                submit = form.get_by_role("button", name="Войти", exact=True)
                if submit.count() == 0:
                    submit = page.get_by_role("button", name="Войти", exact=True).last
                if submit.count() == 0:
                    submit = form.locator('input[type="submit"]').first

                submit.wait_for(state="visible", timeout=self.timeout * 1000)
                submit.click()

                # Give the JS login request/navigation time to finish.
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)

                current_url = page.url.lower()
                text = page.locator("body").inner_text(timeout=5000).lower()

                bad = (
                    "неверный пароль",
                    "неверный логин",
                    "неверные учетные данные",
                    "ошибка авторизации",
                    "не удалось войти",
                )
                good = (
                    "личный кабинет",
                    "выйти",
                    "logout",
                    "личные данные",
                )

                # A successful login normally leaves /login.html. Also accept
                # explicit authenticated UI markers on the resulting page.
                left_login = "/login.html" not in current_url
                authenticated = (left_login or any(x in text for x in good)) and not any(
                    x in text for x in bad
                )

                cookies = context.cookies()
                if authenticated and cookies:
                    for cookie in cookies:
                        self.session.cookies.set(
                            cookie["name"],
                            cookie["value"],
                            domain=cookie.get("domain"),
                            path=cookie.get("path", "/"),
                        )
                    logger.info(
                        "B2B-Center: browser login succeeded; cookies=%d",
                        len(cookies),
                    )
                else:
                    logger.warning(
                        "B2B-Center: login check failed; url=%s cookies=%d",
                        page.url,
                        len(cookies),
                    )
                    authenticated = False

                browser.close()
                return authenticated
        except Exception:
            logger.exception("B2B-Center: ошибка браузерной авторизации")
            return False
