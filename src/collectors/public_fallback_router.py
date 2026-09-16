"""Last-resort public search routing for blocked procurement portals.

The first-party collector always runs first.  When the portal is unavailable
or explicitly blocked, the router uses TenderGuru's public thematic indexes to
keep keyword search operational without bypassing authentication, CAPTCHAs or
other access controls.  Returned records retain the requested logical platform
and carry adapter provenance in ``raw_data``.
"""
from __future__ import annotations

import logging
from typing import Any

from src.collectors.base import CollectorUnavailableError
from src.collectors.tenderguru_fallback import search as tenderguru_search
from src.models.tender import Tender

logger = logging.getLogger(__name__)


class PublicFallbackRouter:
    """Proxy a collector and recover external-access failures via public data."""

    def __init__(self, collector: Any, config: dict | None = None) -> None:
        self._collector = collector
        self.config = config or {}
        self.platform = collector.platform
        self.enabled = bool(self.config.get("public_fallback", True))
        self.timeout = int(self.config.get("timeout_seconds", 20))
        self.max_results = int(self.config.get("max_results", 100))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._collector, name)

    def search(self, keywords: list[str], since=None) -> list[Tender]:
        try:
            return self._collector.search(keywords, since=since)
        except CollectorUnavailableError as exc:
            if not self.enabled:
                raise
            logger.warning(
                "%s: first-party collector unavailable; switching to public fallback: %s",
                self.platform,
                exc,
            )
            return self._fallback_search(keywords, exc)

    def _fallback_search(self, keywords: list[str], reason: Exception) -> list[Tender]:
        merged: dict[str, Tender] = {}
        for keyword in keywords:
            keyword = str(keyword).strip()
            if not keyword:
                continue
            try:
                found = tenderguru_search(
                    platform=self.platform,
                    keyword=keyword,
                    timeout=min(max(self.timeout, 10), 20),
                    max_results=self.max_results,
                )
            except Exception as exc:
                logger.warning("%s: public fallback failed for %r: %s", self.platform, keyword, exc)
                continue
            for tender in found:
                tender.raw_data.setdefault("adapter_mode", "tenderguru_public_fallback")
                tender.raw_data.setdefault("direct_portal_error", str(reason))
                tender.raw_data.setdefault("requested_keyword", keyword)
                merged[tender.unique_key] = tender
                if len(merged) >= self.max_results:
                    return list(merged.values())[: self.max_results]
        if not merged:
            raise CollectorUnavailableError(
                f"{self.platform}: first-party search failed and public fallback returned no results"
            ) from reason
        return list(merged.values())[: self.max_results]

    def get_details(self, external_id: str):
        return self._collector.get_details(external_id)
