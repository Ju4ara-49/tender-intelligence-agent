"""Broad-discovery registry helper."""

from __future__ import annotations

from src.collectors._broad_defaults import broaden_discovery_config


def broad_platform_config(config: dict, platform: str) -> dict:
    """Return a platform config with broad discovery limits."""
    return broaden_discovery_config(
        config.get("collectors", {}).get(platform, {})
    )
