"""Logging helpers safe for Windows file locking."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler


class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that survives Windows file-lock errors during rollover.

    On Windows, another process (or the same process with an open handle) may
    lock ``agent.log`` while rollover tries to rename it to ``agent.log.1``,
    causing ``PermissionError: [WinError 32]``.  The application must keep
    running and continue logging to the current file.
    """

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError as exc:
            logging.getLogger(__name__).warning(
                "Log rollover skipped (file locked): %s", exc,
            )
        except OSError as exc:
            # WinError 32 is PermissionError on modern Python; catch OSError too.
            if getattr(exc, "winerror", None) == 32:
                logging.getLogger(__name__).warning(
                    "Log rollover skipped (WinError 32): %s", exc,
                )
            else:
                raise
