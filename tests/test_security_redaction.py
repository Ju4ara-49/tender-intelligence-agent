"""Regression-тесты P0: Telegram bot token не должен попадать в логи."""

from __future__ import annotations

import logging

import httpx
import pytest

from src.security_redaction import REDACTED, SecretRedactionFilter, SecretRedactionFormatter, redact_secrets

# Синтетический fake token — НЕ настоящий секрет.
FAKE_TOKEN = "123456789:AAFakeTokenForTests_DO_NOT_USE_abcdef12345"
FAKE_URL = f"https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates"


def _make_record(msg: str, args=(), exc: BaseException | None = None) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test", level=logging.ERROR, pathname=__file__, lineno=1,
        msg=msg, args=args, exc_info=(type(exc), exc, exc.__traceback__) if exc else None,
    )
    return record


class TestRedactSecrets:
    def test_token_in_url_is_redacted(self):
        cleaned = redact_secrets(f"HTTPStatusError for url '{FAKE_URL}'")
        assert FAKE_TOKEN not in cleaned
        assert "api.telegram.org/bot" + REDACTED in cleaned

    def test_bare_token_in_exception_string_is_redacted(self):
        exc = httpx.HTTPStatusError(
            f"Client error '409 Conflict' for url '{FAKE_URL}'",
            request=httpx.Request("GET", FAKE_URL),
            response=httpx.Response(409, request=httpx.Request("GET", FAKE_URL)),
        )
        cleaned = redact_secrets(str(exc))
        assert FAKE_TOKEN not in cleaned
        assert "409 Conflict" in cleaned

    def test_known_token_replaced_anywhere(self):
        cleaned = redact_secrets(f"weird place {FAKE_TOKEN} mid-text", (FAKE_TOKEN,))
        assert FAKE_TOKEN not in cleaned

    def test_useful_info_preserved(self):
        text = f"Client error '500 Internal Server Error' for url '{FAKE_URL}'"
        cleaned = redact_secrets(text)
        assert "500 Internal Server Error" in cleaned
        assert "api.telegram.org" in cleaned

    def test_non_telegram_urls_untouched(self):
        text = "GET https://example.com/api/bot123456:short/values"
        assert redact_secrets(text) == text


class TestSecretRedactionFilter:
    def test_filter_redacts_message_args(self):
        f = SecretRedactionFilter((FAKE_TOKEN,))
        record = _make_record("error: %s", (f"url {FAKE_URL}",))
        assert f.filter(record) is True
        formatted = record.getMessage()
        assert FAKE_TOKEN not in formatted
        assert "error: url" in formatted

    def test_filter_redacts_exception_text(self):
        """Formatter (используемый handler'ом) маскирует token из traceback."""
        formatter = SecretRedactionFormatter(known_tokens=(FAKE_TOKEN,))
        exc = httpx.ConnectError(f"Connection failed for {FAKE_URL}")
        record = _make_record("polling failed", exc=exc)
        assert formatter.format(record) is not None
        formatted = formatter.formatException((type(exc), exc, exc.__traceback__))
        assert FAKE_TOKEN not in formatted
        assert "Connection failed" in formatted
        assert "api.telegram.org" in formatted


class TestEndToEndLogging:
    def test_logger_exception_does_not_leak_token(self, tmp_path, caplog):
        """Полный путь: exception с URL c токеном -> logging -> запись без токена."""
        handler_file = tmp_path / "test.log"
        formatter = SecretRedactionFormatter(known_tokens=(FAKE_TOKEN,))
        file_handler = logging.FileHandler(handler_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(SecretRedactionFilter((FAKE_TOKEN,)))
        logger = logging.getLogger("p0_regression")
        logger.setLevel(logging.ERROR)
        logger.addHandler(file_handler)

        exc = httpx.HTTPStatusError(
            f"Client error '409 Conflict' for url '{FAKE_URL}'",
            request=httpx.Request("POST", FAKE_URL),
            response=httpx.Response(409, request=httpx.Request("POST", FAKE_URL)),
        )
        try:
            raise exc
        except httpx.HTTPError:
            logger.exception("Telegram-бот: ошибка polling, продолжаем через 5 сек")
        file_handler.flush()
        file_handler.close()

        content = handler_file.read_text(encoding="utf-8")
        assert FAKE_TOKEN not in content
        assert "409 Conflict" in content
        assert "Traceback" in content
        logger.removeHandler(file_handler)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
