# Risk Engine checkpoint — 2026-09-18

## Scope
- Deterministic `RiskEngine` already present in `src/risk/engine.py`.
- Regression coverage exists in `tests/test_risk_engine.py`.
- This block adds SQLite persistence in `src/risk/storage.py` and round-trip tests in `tests/test_risk_storage.py`.

## Design
- Risk calculation remains independent of LLM/Ollama.
- Stored assessment contains level, structured factors and UTC assessment timestamp.
- Upsert semantics keep one current assessment per tender.
- Persistence is isolated from the existing `TenderDatabase` API until integration tests prove the integration path.

## Next
- Integrate assessment calculation into the orchestrator after tender persistence.
- Surface risk in Telegram and Excel.
- Add Ollama explanation as optional presentation only; deterministic level/factors remain source of truth.
