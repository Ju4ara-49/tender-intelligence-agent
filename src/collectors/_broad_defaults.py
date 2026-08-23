"""Shared broad-discovery defaults for tender collectors."""

# Discovery is intentionally generous: a result page is not the search.
# Collectors may use a higher explicit value, but a legacy low value should not
# silently reduce a multi-platform search to a handful of procedures.
DEFAULT_DISCOVERY_MAX_RESULTS = 500
DEFAULT_DISCOVERY_MAX_PAGES = 20


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
