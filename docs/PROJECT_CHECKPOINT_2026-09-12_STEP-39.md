# Project checkpoint — 2026-09-12 — STEP-39

## Completed CI run

- Workflow: `Tender Intelligence Agent CI`
- Run: `34695253240` / run number `431`
- Commit: `c810b2fa7203b33d4b3dbba361750a8f1afb8904`
- Result: **SUCCESS**

## Verified production change

The active `FabrikantV3Collector` now overrides the inherited procedure-link resolver so relative links are resolved against the current Fabrikant host (`soap2` for 223-FZ or `soap4` for 44-FZ) instead of the old hard-coded `soap4` host.

A new regression test covers a relative 223-FZ procedure link and verifies that the rich registry row remains populated with:

- title;
- customer;
- price;
- publication date;
- deadline;
- law type;
- search-row mapping;
- stored detail URL.

The full CI suite passed with this change.

## Pending

The live browser diagnostics run for the same commit remains separate and must be checkpointed after completion.
