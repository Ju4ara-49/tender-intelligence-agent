# Search architecture audit

## Goal

Make Tender Intelligence Agent search broadly and consistently across every enabled procurement platform, while keeping the existing B2B-Center modern collector intact.

## Findings from the current `main` branch

- `Orchestrator.run_cycle()` sends the same user keyword list to every enabled collector and relies on each collector to implement breadth and pagination.
- The collector registry currently supports EIS, B2B-Center, Fabrikant, RTS-Tender, TMK and Rosatom.
- Telegram platform selection is intentionally authoritative: when Telegram supplies a platform list, it overrides the static `enabled` flags.
- The generic browser collector for RTS/TMK currently performs one browser search per keyword and parses links from the rendered DOM. It has a `max_results` cap but no generic pagination mechanism.
- B2B-Center's modern collector uses `/app/next/market-search`, but the current run demonstrated only 20 accepted results per keyword and only 20 unique B2B procedures across three keywords. This indicates that the current modern-search path is still effectively bounded by the first rendered result page or by the portal's result window.
- The current pipeline then performs expensive detail loading only after keyword filtering. This is correct for cost control, but broad discovery must happen before that stage.

## Required target architecture

1. **Discovery layer**: every collector must expose broad search with configurable page/window limits and stop only when the platform reports no more results or repeated pages produce no new IDs.
2. **Keyword fan-out**: search each Telegram keyword independently; merge by the unified `Tender.unique_key`.
3. **Platform isolation**: one broken platform must not reduce results from the others. Failures are logged per platform and search continues.
4. **Unified normalization**: every collector returns `Tender` objects; publication date, deadline, price, customer and region are normalized at the unified boundary.
5. **Cheap filtering before details** where the search row contains enough information; otherwise enrich only candidates that survive discovery-level filters.
6. **Detail enrichment**: detail loading must preserve authoritative search-row values when the detail page contains historical or unrelated dates.
7. **Deduplication**: duplicates are removed across keywords and within each platform, but a previously seen database tender must still remain in the current Excel result if it matches the current search.
8. **Diagnostics**: each platform must report `pages_attempted`, `raw_results`, `unique_results`, `stopped_reason` and errors, so a low-result search can be diagnosed instead of silently accepted.
9. **Configurable breadth**: no hard-coded 20/50-result ceiling in application code. Limits must come from platform configuration with safe defaults.
10. **B2B-Center protection**: do not replace the existing modern `/app/next/market-search` parser or revert the confirmed title extraction work. Improve it incrementally with explicit pagination/window handling and diagnostics.

## Acceptance criteria

A search such as `Подшипники`, `муфты`, `редуктор` with all Telegram platforms enabled must:

- invoke every selected platform;
- collect more than the first 20 procedures when the platform exposes additional pages/results;
- merge results across all keywords without losing unique procedures;
- continue when one platform fails;
- produce per-platform counts in the log;
- preserve the existing Excel/Telegram/AI pipeline;
- keep B2B-Center title and detail parsing intact;
- avoid credentials and Telegram tokens in source control.

This document is an implementation target, not a replacement for platform-specific tests. Each platform must be verified against its live search UI/API before claiming full coverage.
