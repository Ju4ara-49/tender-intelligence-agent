# kilo — B2B quality gate and EIS contracts

Branch: `ai/kilo-b2b-eis` (base `feature/search-ux-enhancements-2026-09-20`).
Scope: `src/collectors/b2b_center*.py`, `src/collectors/eis_*.py`,
`src/collectors/detail_contract.py`, regression tests, this report.

## Findings

### 1. B2B quality gate could be passed without a detail page (fixed)

`B2BCenterCollector.get_details` caught every parsing/HTTP error and returned
a discovery-derived fallback tender whose only "not loaded" marker was
`raw_data["details_loaded"] = False`.

That marker is not authoritative:

* `detail_contract.enforce_detail_contract` (applied to every registry
  collector) recomputes `raw_data["details_loaded"] = detail_status != "failed"`
  — with the default `"success"` status the flag was turned back into `True`;
* `Orchestrator._merge_detail` does the same from `detailed.detail_status`.

Because `_merge_detail` only copies non-empty values, the discovery row's
`customer`, `price` and `deadline` survive the merge. The result was a B2B
tender with `details_loaded=True` and a populated gate, i.e. a false positive
through `KeywordFilter._b2b_details_are_complete` without any detail page ever
being parsed.

Reproduced before the fix (`enforce_detail_contract` + `Orchestrator._merge_detail`
+ `matches_strict`):

```
detail_status: partial | details_loaded: True
merged status: partial | details_loaded: True
matches_strict: True
```

Fix: the fallback tender now reports `detail_status="failed"` together with
`detail_diagnostics`, so the shared contract and the orchestrator keep
`details_loaded=False` and the strict gate rejects the tender. The gate itself
was not weakened — a successfully parsed detail page still yields
`customer`/`price`/`deadline` and still passes the gate (locked by a test).

### 2. Dead duplicate `_extract_customer_from_soup` in EIS (removed)

`EisZakupkiCollector` defined `_extract_customer_from_soup` twice in one class
body (lines 1179 and 1296 before the change). Only the second definition is
reachable. The dead first copy accepted only budget/legal-entity prefixes and
had no commercial prefixes, so keeping or restoring it would silently drop
customers such as `ООО "Ромашка"`. The dead copy was deleted; behaviour is
locked by tests for a commercial customer, for service table headers, and for
the definition count.

### 3. EIS degraded searches looked healthy (fixed, no behaviour change)

`ReliableEisZakupkiCollector.search` returned rows without recording a
degraded state in two cases:

* RSS succeeded for some keywords and failed for others — the returned set is
  incomplete but the platform reported no error;
* the opt-in public fallback produced rows after a healthy first-party search
  that returned nothing — foreign public-index rows were served as an ordinary
  EIS result set.

Both now set `_last_search_error`, which the orchestrator already surfaces as a
platform error. Fail-closed default behaviour, the opt-in nature of the public
fallback, the degraded markers on fallback tenders and the RSS/CAPTCHA checks
are unchanged.

## Not changed (verified, no defect found)

* B2B offset discovery: `from=0,20,40,60` is requested; `max_pages=1` does not
  collapse discovery (enforced lower bound of 10 pages, plus short-page and
  no-new-id stop conditions).
* `ReliableB2BCenterCollector._parse_search_html` really does defer strict
  relevance: `ModernB2BCenterCollector._parse_search_html` applies no keyword
  gate, so rows whose keyword appears only in lots/specifications reach detail
  loading.
* Orchestrator order is correct: soft filter → detail enrichment → strict
  quality gate. No collector-side change was needed to fix an early gate.
* EIS HTTP 403/5xx, timeouts and CAPTCHA/WWA still surface as
  `CollectorUnavailableError` and are recorded in `_last_search_error` instead
  of being converted into an empty successful result.

## Tests

New: `tests/test_kilo_b2b_eis.py` (11 tests).

* 6 of them fail on the pre-fix sources (`git stash` of the three collector
  files) and pass after the fixes; the remaining 5 lock contracts that must not
  change (commercial customer extraction, service-header rejection, gate pass
  on a loaded detail page, healthy search reports no degraded state, fail-closed
  EIS by default).

Full suite:

* `PYTHONPATH=. python -m pytest -q` → `476 passed, 12 subtests passed`
* `PYTHONPATH=. python -m unittest discover -s tests` → `Ran 92 tests ... OK`