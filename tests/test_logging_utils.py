"""Regression tests for Windows-safe log rotation."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

from src.logging_utils import SafeRotatingFileHandler


def test_safe_rotating_handler_survives_permission_error_on_rollover(tmp_path: Path) -> None:
    log_file = tmp_path / "agent.log"
    handler = SafeRotatingFileHandler(
        log_file,
        maxBytes=10,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("test_logging_utils")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    with patch.object(
        logging.handlers.RotatingFileHandler,
        "doRollover",
        side_effect=PermissionError(13, "Permission denied"),
    ):
        logger.info("x" * 50)

    assert log_file.exists()
    handler.close()
