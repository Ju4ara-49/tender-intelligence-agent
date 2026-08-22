"""Реестр сборщиков — точка регистрации новых площадок."""

from __future__ import annotations

from typing import Type

from src.collectors.base import BaseCollector
from src.collectors.b2b_center_auth_v2 import AuthenticatedB2BCenterCollector
from src.collectors.browser_public import RtsTenderCollector, TmkCollector
from src.collectors.eis_zakupki import EisZakupkiCollector
from src.collectors.rosatom import RosatomCollector
from src.collectors.unipro import UniproCollector


# Все поддерживаемые площадки. Конкретное включение управляется Telegram.
# config.yaml остаётся резервной настройкой: если пользователь явно выбрал
# площадку в Telegram, она должна быть создана даже при старой/неполной
# локальной конфигурации без enabled: true.
ALL_COLLECTORS: list[Type[BaseCollector]] = [
    EisZakupkiCollector,
    AuthenticatedB2BCenterCollector,
    UniproCollector,
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
    и он имеет приоритет над устаревшим enabled-флагом в config.yaml.
    Это особенно важно после добавления новых площадок: старый локальный
    config.yaml не должен молча отключать новую площадку.

    Если Telegram-список не передан, используется config.yaml.
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

        if selected is not None:
            # Telegram — главный переключатель площадок. Если площадка выбрана,
            # не блокируем её старым enabled=false/отсутствующей секцией.
            if instance.platform not in selected:
                continue
        elif not instance.is_enabled(config):
            continue

        platform_config = instance.get_platform_config(config)
        enabled.append(collector_cls(platform_config))

    return enabled
