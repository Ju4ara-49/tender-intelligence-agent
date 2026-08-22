"""Compatibility registration for additional tender platforms.

Rosatom is now a first-class platform in ``telegram_settings.SUPPORTED_PLATFORMS``
and in the collector registry. This module is intentionally kept as a small
compatibility hook for older imports; it must not override a user's explicit
Telegram platform selection.
"""
from __future__ import annotations

from src.telegram_bot import PLATFORM_NAMES
from src.telegram_settings import SUPPORTED_PLATFORMS


ROSATOM_PLATFORM = "rosatom"
ROSATOM_NAME = "Росатом"

# Keep the registration idempotent for older deployments/import order.
if ROSATOM_PLATFORM not in SUPPORTED_PLATFORMS:
    SUPPORTED_PLATFORMS.append(ROSATOM_PLATFORM)
PLATFORM_NAMES[ROSATOM_PLATFORM] = ROSATOM_NAME
