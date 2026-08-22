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
    """B2B-Center collector with persistent browser authentication.

    Credentials are read only from local environment variables. On the first
    setup, a headed browser can be used for a normal human login. After that,
    Playwright stores the authenticated browser state locally and reuses it.
    The stored state is never committed to GitHub.
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.authenticated = False
        self.username = os.getenv("B2B_CENTER_USERNAME", "").strip()
        self.password = os.getenv("B2B_CENTER_PASSWORD", "")
        self.manual_login = os.getenv("B2B_CENTER_MANUAL_LOGIN", "").strip().lower() in {
            "1", "true", "yes", "on"
        }

        if not self.username or not self.password:
            logger.info("B2B-Center: логин/пароль не заданы; используется открытый доступ")
            return

        self.authenticated = self._login_with_browser(headless=True)

        # B2B-Center may reject headless/browser automation. For first-time
        # setup, allow a normal visible browser login and persist the state.
        if not self.authenticated and self.manual_login:
            logger.info("B2B-Center: запускаю ручную авторизацию в окне браузера")
            self.authenticated = self._login_with_browser(headless=False)

        if self.authenticated:
            logger.info("B2B-Center: авторизация выполнена успешно")
        else:
            logger.warning("B2B-Center: авторизация не выполнена; используется открытый доступ")

    def _login_with_browser(self, *, headless: bool) -> bool:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error(
                "B2B-Center: для авторизации требуется Playwright. "
                "Установите: pip install -r requirements-b2b-browser.txt"
            )
            return False

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=headless)
                STORAGE_STATE.parent.mkdir(parents=True, exist_ok=True)

                context_kwargs = {
                    "user_agent": self.session.headers.get("User-Agent"),
                }
                if STORAGE_STATE.exists():
                    context_kwargs["storage_state"] = str(STORAGE_STATE)

                context = browser.new_context(**context_kwargs)
                page = context.new_page()
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=self.timeout * 1000)

                # First try the already stored session. This avoids logging in
                # on every bot restart.
                if self._page_is_authenticated(page):
                    self._copy_cookies(context)
                    browser.close()
                    return True

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

                form = password_field.locator("xpath=ancestor::form[1]")
                submit = form.get_by_role("button", name="Войти", exact=True)
                if submit.count() == 0:
                    submit = page.get_by_role("button", name="Войти", exact=True).last
                if submit.count() == 0:
                    submit = form.locator('input[type="submit"]').first
                submit.wait_for(state="visible", timeout=self.timeout * 1000)
                submit.click()

                if not headless:
                    # Give a human time to complete any CAPTCHA, confirmation,
                    # or additional security step shown by the site.
                    logger.info(
                        "B2B-Center: если сайт запросил дополнительное действие, "
                        "выполните его в открывшемся браузере."
                    )
                    page.wait_for_timeout(1500)
                    page.wait_for_url("**", timeout=60000)
                else:
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    page.wait_for_timeout(2000)

                authenticated = self._page_is_authenticated(page)
                cookies = context.cookies()

                if authenticated and cookies:
                    context.storage_state(path=str(STORAGE_STATE))
                    self._copy_cookies(context)
                    logger.info(
                        "B2B-Center: browser login succeeded; cookies=%d; state=%s",
                        len(cookies), STORAGE_STATE,
                    )
                else:
                    logger.warning(
                        "B2B-Center: login check failed; url=%s cookies=%d",
                        page.url, len(cookies),
                    )
                    authenticated = False

                browser.close()
                return authenticated
        except Exception:
            logger.exception("B2B-Center: ошибка браузерной авторизации")
            return False

    @staticmethod
    def _page_is_authenticated(page) -> bool:
        try:
            current_url = page.url.lower()
            text = page.locator("body").inner_text(timeout=5000).lower()
        except Exception:
            return False

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
        left_login = "/login.html" not in current_url
        return (left_login or any(x in text for x in good)) and not any(x in text for x in bad)

    def _copy_cookies(self, context) -> None:
        for cookie in context.cookies():
            self.session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )
