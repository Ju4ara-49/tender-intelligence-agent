"""Shared helper for broad collector discovery configuration."""

from __future__ import annotations

from src.collectors._broad_defaults import broaden_discovery_config


def broad_platform_config(config: dict, platform: str) -> dict:
    return broaden_discovery_config(config.get("collectors", {}).get(platform, {}))
