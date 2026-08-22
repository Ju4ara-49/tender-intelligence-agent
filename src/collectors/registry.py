"""Реестр сборщиков — точка регистрации новых площадок."""

from __future__ import annotations

from typing import Type

from src.collectors.base import BaseCollector
from src.collectors.b2b_center_auth_v2 import AuthenticatedB2BCenterCollector
from src.collectors.browser_public import RtsTenderCollector, TmkCollector
from src.collectors.eis_zakupki import EisZakupkiCollector
from src.collectors.fabrikant_v2 import FabrikantV2Collector
from src.collectors.rosatom import RosatomCollector


# Все поддерживаемые площадки. Конкретное включение управляется Telegram.
ALL_COLLECTORS: list[Type[BaseCollector]] = [
    EisZakupkiCollector,
    AuthenticatedB2BCenterCollector,
    FabrikantV2Collector,
    RtsTenderCollector,
    TmkCollector,
    RosatomCollector,
]


def get_enabled_collectors(
    config: dict,
    enabled_platforms: list[str] | None = None,
) -> list[BaseCollector]:
    """Создать экземпляры выбранных сборщиков.

    Если Telegram передал список площадок, это явный пользовательский выбор
    и он имеет приоритет над enabled-флагом в config.yaml.
    """
    enabled: list[BaseCollector] = []
    selected = None
    if enabled_platforms is not None:
        selected = {str(platform).strip() for platform in enabled_platforms if str(platform).strip()}

    for collector_cls in ALL_COLLECTORS:
        instance = collector_cls()
        if selected is not None:
            if instance.platform not in selected:
                continue
        elif not instance.is_enabled(config):
            continue

        platform_config = instance.get_platform_config(config)
        enabled.append(collector_cls(platform_config))

    return enabled
