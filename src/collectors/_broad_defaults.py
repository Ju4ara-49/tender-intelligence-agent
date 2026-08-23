"""Shared broad-discovery defaults for tender collectors."""

DEFAULT_DISCOVERY_MAX_RESULTS = 200
DEFAULT_DISCOVERY_MAX_PAGES = 10


def broaden_discovery_config(platform_config: dict) -> dict:
    """Raise legacy low discovery caps while preserving higher user values."""
    result = dict(platform_config or {})

    try:
        result["max_results"] = max(
            int(result.get("max_results", 0)),
            DEFAULT_DISCOVERY_MAX_RESULTS,
        )
    except (TypeError, ValueError):
        result["max_results"] = DEFAULT_DISCOVERY_MAX_RESULTS

    try:
        result["max_pages"] = max(
            int(result.get("max_pages", 0)),
            DEFAULT_DISCOVERY_MAX_PAGES,
        )
    except (TypeError, ValueError):
        result["max_pages"] = DEFAULT_DISCOVERY_MAX_PAGES

    return result
