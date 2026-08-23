# CHECKPOINT — 2026-08-23

## Current main

The working branch contains the multi-platform search diagnostics and the first production-safety fixes for incomplete B2B-Center results.

## Confirmed problem

B2B-Center discovery can produce a skeleton Tender containing only external ID/title/URL when authenticated detail loading fails or the fallback parser is used. The orchestrator previously allowed such objects to continue to strict filtering, AI, Telegram and Excel.

Example observed in Telegram: tender `4564558` had a date and URL but no customer, region, price, deadline or law.

## Fix now in main

`src/filters/keyword_filter.py`

The strict post-filter now rejects a B2B-Center result when:

- detail enrichment was not successfully loaded;
- customer is empty;
- price is missing;
- submission deadline is missing.

This is deliberately applied only to `b2b_center`; other platforms keep their existing semantics.

Regression tests:

- `tests/test_b2b_quality_gate.py`
  - rejects incomplete B2B cards;
  - rejects B2B cards without loaded details;
  - keeps complete B2B cards;
  - does not impose the B2B gate on other platforms.

CI now runs this test.

## Browser portal hardening

`src/collectors/browser_public_reliable.py` now:

- dismisses common cookie/consent overlays;
- searches across main frame and embedded frames;
- recognizes more search input variants;
- verifies that the requested keyword was actually entered;
- keeps the existing fail-closed behavior when no search control is found.

## External observation

The public Rosatom portal is currently returning a WAF block page to automated/public retrieval. The collector must not bypass WAF or other access controls; it reports the outage instead of fabricating results.

TMK's public portal currently requires JavaScript and cookies, so the browser collector is the correct integration direction.

## Next local validation

After syncing the local checkout to the latest `main`, run the bot and perform one controlled search for `подшипники` with all desired platforms enabled.

The expected behavior is:

- no incomplete B2B cards in Telegram/Excel;
- browser platforms either return real procedures or explicitly report a platform search failure in diagnostics rather than silently disappearing.
