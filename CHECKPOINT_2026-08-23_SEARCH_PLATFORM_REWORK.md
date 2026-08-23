# CHECKPOINT — 2026-08-23 — Search platform rework

## Verified from local Search #068 log

The new multi-platform orchestrator is running, but the real search quality is still uneven:

- EIS: 2 raw results for `Станок` in the observed run.
- B2B-Center: 20 raw results, but all 20 were removed by the strict relevance filter because the returned procedures were unrelated to `Станок`.
- Fabrikant: 1 unique procedure after internal merge.
- RTS-Tender: search field was not found.
- TMK: search field was not found.
- Rosatom: search field was not found.

## Changes committed directly to main

1. `src/collectors/b2b_center_reliable.py`
   - public B2B-Center `/market/` discovery;
   - `f_keyword` + `searching=1`;
   - offset pagination via `from`;
   - up to 50 pages, configurable;
   - relevance gate with small Russian morphology tolerance.

2. `src/collectors/registry.py`
   - B2B-Center now uses `ReliableB2BCenterCollector`;
   - RTS, TMK and Rosatom use resilient browser-search adapters.

3. `src/collectors/browser_public_reliable.py`
   - delayed-widget tolerance;
   - search in main page and same-origin frames;
   - role textbox / input / textarea / contenteditable fallbacks;
   - search-button fallback;
   - bounded result expansion and pagination clicks.

4. `tests/test_b2b_reliable_adapter.py`
   - deterministic relevance test;
   - deterministic offset-pagination test.

5. `.github/workflows/ci.yml`
   - new B2B reliable adapter tests run in CI.

6. `.github/workflows/platform-browser-diagnostics.yml`
   - automated Playwright diagnostics for RTS-Tender, TMK and Rosatom;
   - screenshots and JSON report uploaded as an artifact;
   - diagnostic job is non-blocking.

## Important limitation

The GitHub connector can create commits and inspect repository files, commits and CI status, but it does not expose a direct arbitrary-shell runner for this repository. Therefore the real Telegram/Ollama/Playwright end-to-end run still requires the local machine unless GitHub Actions provides the needed environment and its run/artifact identifiers become accessible.

## Next verification target

Run Telegram search with keyword `Станок` after pulling `main` and compare:

- B2B-Center raw count > 20 where available;
- B2B-Center relevance exclusions no longer eliminate every result;
- RTS/TMK/Rosatom no longer report `поле поиска не найдено`;
- EIS discovery remains functional;
- details and Excel remain functional.

Do not modify Ollama, Telegram menu layout, Excel architecture, or database notification semantics as part of this search-platform checkpoint.
