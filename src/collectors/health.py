"""Live health diagnostics for configured tender platforms.

The command deliberately exercises each collector's public search path instead
of treating a successful DNS/HTTP request as a healthy integration. A platform
is healthy only when the collector can reach its public search UI/API and parse
at least one tender for the probe query. Access blocks, WAFs and network
failures are reported separately and never silently converted to zero results.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from src.collectors.registry import get_enabled_collectors

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlatformHealth:
    platform: str
    status: str
    elapsed_seconds: float
    results: int = 0
    error: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_platforms(
    config: dict,
    *,
    query: str = "подшипники",
    platforms: list[str] | None = None,
) -> list[PlatformHealth]:
    """Exercise enabled collectors with a bounded live search probe.

    ``status`` values:
    - ``ok`` — search was submitted and at least one procedure was parsed;
    - ``zero_results`` — connection/search path worked but parser returned no
      procedure (usually a selector/query regression and therefore suspicious);
    - ``error`` — collector raised or the platform was unreachable/blocked.
    """
    collectors = get_enabled_collectors(config, enabled_platforms=platforms)
    report: list[PlatformHealth] = []
    for collector in collectors:
        started = time.monotonic()
        try:
            logger.info("PLATFORM_HEALTH_START platform=%s query=%r", collector.platform, query)
            found = collector.search([query], since=datetime.now(timezone.utc)) or []
            elapsed = round(time.monotonic() - started, 2)
            if found:
                report.append(
                    PlatformHealth(
                        platform=collector.platform,
                        status="ok",
                        elapsed_seconds=elapsed,
                        results=len(found),
                        detail="live search returned parsed procedures",
                    )
                )
            else:
                report.append(
                    PlatformHealth(
                        platform=collector.platform,
                        status="zero_results",
                        elapsed_seconds=elapsed,
                        detail=(
                            "search returned no parsed procedures; inspect logs for "
                            "WAF/network/search-adapter/parser diagnostics"
                        ),
                    )
                )
        except Exception as exc:  # health command must report every platform
            elapsed = round(time.monotonic() - started, 2)
            logger.exception("PLATFORM_HEALTH_ERROR platform=%s", collector.platform)
            report.append(
                PlatformHealth(
                    platform=collector.platform,
                    status="error",
                    elapsed_seconds=elapsed,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return report
