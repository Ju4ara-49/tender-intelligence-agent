"""Авторизация B2B-Center поверх существующего сборщика."""

from __future__ import annotations

import logging
import os
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.collectors.b2b_center import B2BCenterCollector


logger = logging.getLogger(__name__)

BASE_URL = "https://www.b2b-center.ru"
LOGIN_URL_CANDIDATES = (
    f"{BASE_URL}/app/next/login/",
    f"{BASE_URL}/login/",
    f"{BASE_URL}/members/login.html",
    f"{BASE_URL}/members/login/",
)


class AuthenticatedB2BCenterCollector(B2BCenterCollector):
    """B2B-Center collector with optional login/password authentication.

    Credentials are read only from environment variables and are never
    written to the repository or logs.
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.authenticated = False

        username = os.getenv("B2B_CENTER_USERNAME", "").strip()
        password = os.getenv("B2B_CENTER_PASSWORD", "")

        if not username or not password:
            logger.info(
                "B2B-Center: логин/пароль не заданы; используется открытый доступ"
            )
            return

        self.authenticated = self._login(username, password)

        if self.authenticated:
            logger.info(
                "B2B-Center: авторизация выполнена успешно"
            )
        else:
            logger.warning(
                "B2B-Center: авторизация не выполнена; продолжаем с текущей сессией"
            )

    def _login(self, username: str, password: str) -> bool:
        """Find the current login form and submit it using the same session."""

        for login_url in LOGIN_URL_CANDIDATES:
            try:
                response = self.session.get(
                    login_url,
                    timeout=self.timeout,
                    allow_redirects=True,
                )

                if response.status_code >= 400:
                    continue

                soup = BeautifulSoup(response.text, "lxml")
                form = None

                for candidate in soup.find_all("form"):
                    password_input = candidate.find(
                        "input",
                        attrs={"type": "password"},
                    )
                    if password_input is not None:
                        form = candidate
                        break

                if form is None:
                    continue

                data: dict[str, str] = {}

                for hidden in form.find_all(
                    "input",
                    attrs={"type": "hidden"},
                ):
                    name = hidden.get("name")
                    if name:
                        data[str(name)] = str(
                            hidden.get("value", "")
                        )

                password_input = form.find(
                    "input",
                    attrs={"type": "password"},
                )
                if password_input is None:
                    continue

                password_name = str(
                    password_input.get("name") or "password"
                )
                data[password_name] = password

                username_input = self._find_username_input(form)
                if username_input is None:
                    logger.warning(
                        "B2B-Center: поле логина не найдено на %s",
                        response.url,
                    )
                    continue

                username_name = str(
                    username_input.get("name") or "login"
                )
                data[username_name] = username

                action = str(form.get("action") or response.url)
                action_url = urljoin(response.url, action)

                submit = self.session.post(
                    action_url,
                    data=data,
                    timeout=self.timeout,
                    allow_redirects=True,
                )

                if self._looks_authenticated(submit):
                    return True

            except requests.RequestException:
                logger.exception(
                    "B2B-Center: ошибка HTTP при авторизации"
                )
            except Exception:
                logger.exception(
                    "B2B-Center: непредвиденная ошибка авторизации"
                )

        return False

    @staticmethod
    def _find_username_input(form):
        """Find login/email/username field without depending on one HTML version."""

        inputs = form.find_all("input")
        preferred = ("login", "email", "username", "user")

        for item in inputs:
            input_type = str(item.get("type", "text")).lower()
            if input_type in {"hidden", "password", "submit", "button"}:
                continue

            name = str(item.get("name", "")).lower()
            field_id = str(item.get("id", "")).lower()
            placeholder = str(item.get("placeholder", "")).lower()
            haystack = f"{name} {field_id} {placeholder}"

            if any(token in haystack for token in preferred):
                return item

        for item in inputs:
            input_type = str(item.get("type", "text")).lower()
            if input_type in {"text", "email"}:
                return item

        return None

    @staticmethod
    def _looks_authenticated(response: requests.Response) -> bool:
        """Check common authenticated-state markers without logging page data."""

        if response.history and any(
            item.status_code in {301, 302, 303, 307, 308}
            for item in response.history
        ):
            if any(
                marker in response.url.lower()
                for marker in ("personal", "account", "cabinet")
            ):
                return True

        text = response.text.lower()
        markers = (
            "личный кабинет",
            "выйти",
            "logout",
            "personal account",
        )
        return any(marker in text for marker in markers)
