# Risk persistence

`RiskAssessmentStore` stores the current deterministic assessment for each tender in SQLite.

- one row per `tender_id`
- structured factor evidence is JSON
- `assessed_at` is normalized to UTC
- save is idempotent/upserted
- retrieval reconstructs `RiskAssessment` / `RiskFactor`

The store intentionally does not calculate risk and does not call Ollama. The deterministic engine remains the source of truth.
