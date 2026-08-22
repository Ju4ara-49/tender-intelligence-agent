"""Compatibility registration for additional tender platforms."""
from __future__ import annotations

from src.telegram_bot import PLATFORM_NAMES
from src.telegram_settings import SUPPORTED_PLATFORMS
from src.collectors.fabrikant import FabrikantCollector
from src.collectors.registry import ALL_COLLECTORS


_EXTRA_PLATFORMS = {
    "rosatom": "Росатом",
    "fabrikant": "Фабрикант",
}

for platform, name in _EXTRA_PLATFORMS.items():
    if platform not in SUPPORTED_PLATFORMS:
        SUPPORTED_PLATFORMS.append(platform)
    PLATFORM_NAMES[platform] = name

# Backward-compatible runtime registration. This is intentionally idempotent.
if not any(cls.platform == FabrikantCollector.platform for cls in ALL_COLLECTORS):
    ALL_COLLECTORS.append(FabrikantCollector)
