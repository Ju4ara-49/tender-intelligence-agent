"""Реестр сборщиков — точка регистрации новых площадок."""

from __future__ import annotations

from typing import Type

from src.collectors._broad_defaults import broaden_discovery_config
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


# Все поддерживаемые площадки. Конкретное включение определяется одновременно
# конфигурацией приложения и пользовательским выбором в Telegram.
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

    Без явного пользовательского списка используются только площадки с
    ``enabled: true`` в config.yaml. При наличии списка из Telegram он
    дополнительно ограничивает этот набор: пользователь не может включить
    площадку, которую администратор отключил в конфигурации.

    Важное правило: отсутствие секции площадки в конфигурации означает
    ``disabled``, а не ``enabled``. Это особенно важно для браузерных
    сборщиков, у которых исторически был более разрешительный ``is_enabled``.
    Реестр является последней точкой авторизации включения площадки.
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
        platform = str(getattr(collector_cls, "platform", "")).strip()
        if not platform:
            continue

        platform_config = config.get("collectors", {}).get(platform)
        if not isinstance(platform_config, dict) or not bool(platform_config.get("enabled", False)):
            continue
        if selected is not None and platform not in selected:
            continue

        configured = collector_cls(
            broaden_discovery_config(platform_config)
        )
        enforce_detail_contract(configured)
        enabled.append(configured)

    return enabled
