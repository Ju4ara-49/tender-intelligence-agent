# CHECKPOINT — 2026-08-23

## Current main

The working branch contains the multi-platform search diagnostics and production-safety fixes for incomplete B2B-Center results.

## Confirmed Telegram selection path

The Telegram-selected platform list is now explicitly bound to the user's chat context before the background search starts. Regression coverage confirms that the selected platform list reaches the collector registry.

A real run confirmed:

- Telegram selected all six platforms;
- Orchestrator activated all six collectors;
- EIS returned results;
- B2B-Center returned results;
- RTS-Tender, TMK, Fabrikant and Rosatom returned `raw=0` at discovery.

Therefore the current failure is inside individual platform discovery/adapters, not Telegram platform selection.

## B2B-Center safety gate

The strict post-filter rejects a B2B-Center result when:

- detail enrichment was not successfully loaded;
- customer is empty;
- price is missing;
- submission deadline is missing.

This prevents skeleton B2B cards such as tender `4564558` from reaching Telegram/Excel.

## Browser portal hardening

`src/collectors/browser_public_reliable.py` now:

- dismisses common cookie/consent overlays;
- searches across main frame and embedded frames;
- recognizes more search input variants;
- verifies that the requested keyword was actually entered;
- keeps fail-closed behavior when no search control is found.

## New SPA result parsing hardening

`src/collectors/browser_public.py` now recognizes procurement navigation rendered by modern SPA applications through:

- `href`;
- `data-href`;
- `data-url`;
- `data-link`;
- `routerlink`;
- `data-routerlink`.

This addresses a common case where the result card is not an ordinary `<a href>` element and previously produced a false `raw=0`.

Regression coverage is in `tests/test_browser_public_parser.py`.

## External observations

The public Rosatom portal has recently returned a WAF block page to automated/public retrieval. The collector must not bypass WAF, CAPTCHA, authentication or other access controls.

TMK's procurement portal is a JavaScript-driven supplier application and requires browser execution/cookies.

## Next validation

After syncing this main branch locally, run the existing browser/parser tests and then one controlled `подшипники` search with all six platforms enabled.

Expected outcome:

- no incomplete B2B cards in Telegram/Excel;
- SPA result links are recognized when exposed through data attributes/router links;
- platforms that remain blocked/unavailable are reported as platform discovery failures rather than silently treated as successful empty searches.
