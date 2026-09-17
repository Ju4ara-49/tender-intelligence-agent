# Risk integration checkpoint

The deterministic Risk Engine is present in `src/risk/engine.py` with regression tests. This branch adds persistence in `src/risk/storage.py` and tests its SQLite round-trip behavior.

Integration into orchestrator/Telegram/Excel remains the next code block and must be verified by the full CI suite before merge.
