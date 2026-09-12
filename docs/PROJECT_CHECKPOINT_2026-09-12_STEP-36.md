# Project checkpoint — 2026-09-12 — STEP-36

## Completed browser diagnostics run

- Workflow: `Platform Browser Diagnostics`
- Run: `34694856148`
- Commit tested: `6974beab9f3fa4ca434a0a8ccb4b2c6515531866`
- Result: **FAIL**

## Finding

B2B-Center returned a real HTTP `403 Forbidden` response from nginx. The diagnostics code incorrectly continued into search-control detection and reported `search_control_missing`.

This was a diagnostics classification defect, not evidence that the B2B search adapter itself is broken.

## Fix committed

The next code change adds:

- explicit classification of HTTP `401`, `403`, and `429` as `access_block`;
- preservation of the HTTP status in the report;
- a regression test for 403/429 and normal 200 status;
- the existing explicit result-count tests remain intact.

The strict gate is preserved: access blocks still fail the live browser gate, but they are now correctly distinguished from application/search defects.

## Other evidence

Fabrikant 223-FZ (`Всего: 0`), Fabrikant 44-FZ (`Всего: 13`) and Rosatom (`Всего: 10`) remained valid live search surfaces. EIS, RTS-Tender and TMK remained transport timeouts.

## Next run

The new access-block classification and regression tests must be validated in the next CI/browser cycle. After that, continue the collector-level audit, especially the active Fabrikant V3/V2 implementation used by the registry.
