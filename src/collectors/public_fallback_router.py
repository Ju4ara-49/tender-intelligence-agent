"""Last-resort public search routing for blocked procurement portals."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.collectors.base import CollectorUnavailableError
from src.collectors.tenderguru_fallback import search as tenderguru_search
from src.models.tender import Tender

logger = logging.getLogger(__name__)


class PublicFallbackRouter:
    """Proxy a collector and recover external-access/zero-result searches."""

    def __init__(self, collector: Any, config: dict | None = None) -> None:
        self._collector = collector
        self.config = config or {}
        self.platform = collector.platform
        self.enabled = bool(self.config.get("public_fallback", True))
        self.fallback_on_empty = bool(self.config.get("public_fallback_on_empty", True))
        self.timeout = int(self.config.get("timeout_seconds", 20))
        self.max_results = int(self.config.get("max_results", 100))
        self._fallback_tenders: dict[str, Tender] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._collector, name)

    def search(self, keywords: list[str], since: datetime | None = None) -> list[Tender]:
        try:
            primary = self._collector.search(keywords, since=since)
        except CollectorUnavailableError as exc:
            if not self.enabled:
                raise
            logger.warning("%s: first-party collector unavailable; switching to public fallback: %s", self.platform, exc)
            return self._fallback_search(keywords, since, exc)
        if primary or not (self.enabled and self.fallback_on_empty):
            return primary
        logger.warning("%s: first-party collector returned zero verified results; probing public fallback", self.platform)
        return self._fallback_search(keywords, since, RuntimeError("first-party search returned zero results"))

    def _fallback_search(self, keywords: list[str], since: datetime | None, reason: Exception) -> list[Tender]:
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
                if since is not None and tender.published_at is not None:
                    published = tender.published_at
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    comparison_since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
                    if published.astimezone(timezone.utc) < comparison_since.astimezone(timezone.utc):
                        continue
                tender.raw_data.setdefault("adapter_mode", "tenderguru_public_fallback")
                tender.raw_data.setdefault("direct_portal_error", str(reason))
                tender.raw_data.setdefault("requested_keyword", keyword)
                tender.raw_data.setdefault("details_loaded", False)
                merged[tender.unique_key] = tender
                self._fallback_tenders[str(tender.external_id)] = tender
                if len(merged) >= self.max_results:
                    return list(merged.values())[: self.max_results]
        if not merged:
            raise CollectorUnavailableError(
                f"{self.platform}: first-party search failed/returned zero and public fallback returned no results"
            ) from reason
        return list(merged.values())[: self.max_results]

    def get_details(self, external_id: str):
        fallback = self._fallback_tenders.get(str(external_id))
        if fallback is not None:
            logger.info("%s: returning public fallback record for %s", self.platform, external_id)
            return fallback
        return self._collector.get_details(external_id)
