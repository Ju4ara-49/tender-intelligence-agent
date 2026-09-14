# Permanent completion algorithm

This project is worked on under a strict no-false-green rule.

## Required loop

1. Continue from the latest `main` repository state; never restart from an old checkpoint.
2. Record the current HEAD before making changes.
3. Audit layer-by-layer: collectors/discovery → detail contract/normalization → filters → dedup/storage/notification fingerprints → AI/Ollama → Telegram/notifications → CRM → Excel → scheduler/orchestrator/CLI → CI/GitHub Actions → live/browser diagnostics.
4. Fix every discovered defect in code; do not merely document it.
5. Add or strengthen a regression test for every meaningful defect.
6. Run the narrowest relevant test, then the complete available suite.
7. Run CI and live/browser diagnostics after code changes.
8. Inspect failures rather than accepting a green-looking summary. Skipped, inconclusive, timed-out, access-blocked or unexecuted checks are not success.
9. If a verification route is blocked by infrastructure or an external platform, use a second independent verification route (fixtures, parser contracts, deterministic integration tests, a legitimate alternate live endpoint, or another runner). Never silently convert an unverified check into SUCCESS.
10. Repeat fix → regression test → full test → CI → live diagnostic until all code-level gates are green and remaining external limitations are proven external rather than project defects.
11. Do not stop because one layer is green; continue through the remaining layers.
12. Do not declare the version fully operational while a discovered code defect, failing test, false-green diagnostic, missing required integration, or unverified required platform remains.

## Definition of done

The version may be called fully operational only when the repository is internally consistent, all available automated tests pass, CI passes on the latest HEAD, browser/platform diagnostics do not hide failures, required collectors are registered/tested, detail normalization and commercial filters have regression coverage, notification delivery is recipient-safe, AI/Ollama failures are explicit, Telegram/CRM/Excel/scheduler paths are covered by tests or deterministic integration checks, generated Excel artifacts pass schema/link checks, and no newly discovered defect is intentionally left unresolved.

Statements such as “not finished yet”, “not declaring fully ready”, or “continue later” are intermediate states only. Continue automatically to the next diagnostic/fix cycle.
