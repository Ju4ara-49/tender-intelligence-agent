"""Реестр сборщиков — точка регистрации новых площадок."""

from __future__ import annotations

from typing import Type

from src.collectors.base import BaseCollector
from src.collectors.b2b_center_reliable import ReliableB2BCenterCollector
from src.collectors.browser_public_reliable import (
    ReliableRosatomCollector,
    ReliableRtsTenderCollector,
    ReliableTmkCollector,
)
from src.collectors.detail_contract import enforce_detail_contract
from src.collectors.eis_reliable import ReliableEisZakupkiCollector
from src.collectors.fabrikant_v3 import FabrikantV3Collector
from src.collectors.public_fallback_router import PublicFallbackRouter


ALL_COLLECTORS: list[Type[BaseCollector]] = [
    ReliableEisZakupkiCollector,
    ReliableB2BCenterCollector,
    FabrikantV3Collector,
    ReliableRtsTenderCollector,
    ReliableTmkCollector,
    ReliableRosatomCollector,
]


def get_enabled_collectors(
    config: dict,
    enabled_platforms: list[str] | None = None,
) -> list[BaseCollector]:
    """Создать экземпляры реально разрешённых сборщиков.

    First-party collectors always remain the primary adapter.  If a public
    portal is unavailable from the current network, the optional fallback
    router preserves keyword-search availability through a public thematic
    index; it never bypasses authentication, CAPTCHA or access controls.
    """
    enabled: list[BaseCollector] = []
    selected = None
    if enabled_platforms is not None:
        selected = {
            str(platform).strip()
            for platform in enabled_platforms
            if str(platform).strip()
        }

    for collector_cls in ALL_COLLECTORS:
        instance = collector_cls()
        platform_config = config.get("collectors", {}).get(instance.platform)
        if not isinstance(platform_config, dict) or not bool(platform_config.get("enabled", False)):
            continue
        if selected is not None and instance.platform not in selected:
            continue

        platform_config = instance.get_platform_config(config)
        configured = collector_cls(platform_config)
        enforce_detail_contract(configured)
        if bool(platform_config.get("public_fallback", True)):
            configured = PublicFallbackRouter(configured, platform_config)
        enabled.append(configured)

    return enabled
