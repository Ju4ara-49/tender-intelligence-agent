"""Централизованная redaction секретов для логирования (P0 security fix).

Единая точка очистки Telegram Bot API секретов из произвольного текста:
URL вида ``https://api.telegram.org/bot<TOKEN>/...``, «голый» токен
``<bot_id>:<secret>`` и известный текущий токен из настроек.
"""

from __future__ import annotations

import logging
import re

TELEGRAM_TOKEN_PATTERN = re.compile(r"(?<![\w-])(\d{6,12}):([A-Za-z0-9_-]{30,})(?![\w-])")
TELEGRAM_BOT_URL_PATTERN = re.compile(r"(api\.telegram\.org/bot)(\d{6,12}):[A-Za-z0-9_-]+")
REDACTED = "[REDACTED]"


def redact_secrets(text: str, known_tokens: "list[str] | tuple[str, ...] | set[str] | None" = None) -> str:
    """Удалить Telegram-секреты из текста, сохранив полезную информацию об ошибке."""
    if not text:
        return text
    result = str(text)
    # 1. Известные текущие токены (в т.ч. внутри exception string).
    for token in known_tokens or ():
        if token and token in result:
            result = result.replace(token, REDACTED)
    # 2. Telegram Bot API URL: https://api.telegram.org/bot<TOKEN>/method
    result = TELEGRAM_BOT_URL_PATTERN.sub(r"\1" + REDACTED, result)
    # 3. Голый токен <bot_id>:<secret> в любом месте строки (exception/traceback).
    result = TELEGRAM_TOKEN_PATTERN.sub(lambda m: f"{m.group(1)}:{REDACTED}", result)
    return result


class SecretRedactionFilter(logging.Filter):
    """Logging filter: маскирует секреты в message, args и exception-тексте записи.

    Устанавливается на handler'ах в setup_logging, поэтому работает и для
    traceback, отформатированных logging (exc_info / logger.exception).
    """

    def __init__(self, known_tokens: "list[str] | tuple[str, ...] | set[str] | None" = None) -> None:
        super().__init__()
        self.known_tokens = [t for t in (known_tokens or ()) if t]

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            if record.args:
                safe_args = tuple(
                    redact_secrets(a, self.known_tokens) if isinstance(a, str) else a for a in record.args
                )
                if safe_args != record.args:
                    record.args = safe_args
                    record.msg = str(record.msg)
            else:
                record.msg = redact_secrets(str(record.msg), self.known_tokens)
        except Exception:  # pragma: no cover - redaction никогда не ломает logging
            pass
        return True


class SecretRedactionFormatter(logging.Formatter):
    """Formatter, который маскирует секреты в итоговой строке, включая traceback.

    Handler-level Filter не видит отформатированный traceback (formatException
    вызывается в Formatter.format на этапе emit), поэтому перехватываем здесь.
    """

    def __init__(self, fmt: str | None = None, datefmt: str | None = None, known_tokens=None) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.known_tokens = [t for t in (known_tokens or ()) if t]

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record), self.known_tokens)

    def formatException(self, ei) -> str:  # noqa: N802
        return redact_secrets(super().formatException(ei), self.known_tokens)



def get_known_telegram_tokens(settings) -> list[str]:
    """Извлечь известные токены из настроек без их вывода."""
    token = getattr(settings, "telegram_bot_token", "") or ""
    return [token] if token else []
