"""Runtime registration for additional tender platforms.

Kept separate from the Telegram UI so new platforms can be added without
rewriting the main bot implementation. The extension is loaded by main.py
before the Telegram bot and CriteriaStore are instantiated.
"""
from __future__ import annotations

from src.telegram_bot import PLATFORM_NAMES
from src.telegram_settings import CriteriaStore, SUPPORTED_PLATFORMS


ROSATOM_PLATFORM = "rosatom"
ROSATOM_NAME = "Росатом"

if ROSATOM_PLATFORM not in SUPPORTED_PLATFORMS:
    SUPPORTED_PLATFORMS.append(ROSATOM_PLATFORM)

PLATFORM_NAMES[ROSATOM_PLATFORM] = ROSATOM_NAME

_original_get_enabled_platforms = CriteriaStore.get_enabled_platforms


def _get_enabled_platforms_with_rosatom(self: CriteriaStore) -> list[str]:
    platforms = list(_original_get_enabled_platforms(self))
    if ROSATOM_PLATFORM not in platforms:
        platforms.append(ROSATOM_PLATFORM)
    return platforms


CriteriaStore.get_enabled_platforms = _get_enabled_platforms_with_rosatom
