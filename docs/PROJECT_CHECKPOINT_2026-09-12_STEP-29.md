# Project checkpoint — 2026-09-12 — STEP-29

## Purpose

Record the completed all-platform browser diagnostics run and the corrective action taken immediately after it.

## Completed run

- Workflow run: `34694197792`
- Tested commit: `7965036a08692ca723a88a5ed8fc9a06975b9fe8`
- Result: **failed**
- Artifact: `platform-browser-diagnostics`

## Evidence from the real GitHub Actions run

The seven-endpoint matrix reached these states:

- B2B-Center: HTTP 200 and usable search surface.
- Fabrikant 223-FZ: HTTP 200; the submitted query was reflected in the URL and the page explicitly reported `Всего: 0`. This is a valid empty search result, not a transport/parser failure.
- Fabrikant 44-FZ: HTTP 200; the submitted query produced an explicit result count (`Всего: 13`).
- Rosatom: HTTP 200; the submitted query produced visible procurement results.
- EIS: browser navigation timed out at 30 seconds.
- RTS-Tender: browser navigation failed with `ERR_CONNECTION_RESET`.
- TMK: browser navigation timed out at 30 seconds.

The first four observations show that the diagnostic itself was capable of reaching and exercising several live Russian procurement portals. The three remaining failures are transport-level failures from the GitHub Actions browser environment; they are not being mislabeled as parser failures.

## Defect found in the diagnostic gate

The previous diagnostics gate considered `no result links` to be a failure. That is incorrect for a valid search which explicitly reports zero procedures. Fabrikant 223-FZ demonstrated this exact case: the query was submitted and the page reported `Всего: 0`, while the page still contained navigation links.

## Fix committed

Commit `9a2feb6e815b65e52a7f6715fd2ba548ce7fa4b5` updates `tests/platform_browser_diagnostics.py` to:

1. extract explicit result counts from common Russian result labels (`Всего: N`, `Актуальных лотов: N`, and `Показаны первые N записей`);
2. treat an explicit count of zero as a successful search-surface check;
3. retain link-based evidence as a fallback only when no explicit count exists;
4. distinguish transport failures, access blocks, search-adapter failures, and missing result-surface evidence in the report;
5. preserve the strict non-zero exit for genuine diagnostic failures.

## Next required verification

The new diagnostic code must now run on GitHub Actions. The next pass must verify that Fabrikant 223-FZ is no longer falsely reported as failed and must separately reassess EIS, RTS-Tender, and TMK transport failures. Those three platforms must not be declared operational until there is real evidence from a supported transport path.

## Rule for subsequent work

Every completed run is followed by a separate checkpoint in `docs/`. A checkpoint-only commit should eventually be excluded from CI triggers so checkpoint creation does not create an endless self-triggering test chain.
