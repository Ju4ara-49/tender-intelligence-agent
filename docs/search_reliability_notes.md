# Search reliability notes

This file records the search architecture decisions for the multi-platform tender search.

- Discovery must be broad and paginated; a single result page is never treated as the full search.
- Platform failures must be isolated from other platforms.
- A zero-result response is not considered a successful empty search when the adapter could not locate or execute its search control.
- B2B-Center public discovery uses the stable `/market/` endpoint with `f_keyword`, `searching=1`, and `from` offset pagination. The JS-heavy modern UI remains useful for details, but discovery should not depend on infinite-scroll behavior.
- Keyword relevance is checked after discovery/enrichment so that a broad source response does not silently become a false positive.
- Safety limits are explicit and configurable.
