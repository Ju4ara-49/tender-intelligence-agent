# Контрольная точка — 2026-09-11 — STEP-03

HEAD: `5fdb1e9c6b8ae2e568f2e4443248348e3d11624b`

## Добавлено
`tests/test_orchestrator_contract.py`:
- проверка полного переноса detail-полей в Tender;
- проверка fallback `end_date → deadline`;
- проверка, что неизвестный postpayment не проходит заданный max;
- проверка, что неизвестная application/contract security не проходит заданный max;
- проверка корректных значений на границе лимитов.

## Следующий шаг
Проверить и исправить persisted data contract: `start_date`/`end_date` и notification fingerprint должны отражать изменения, которые реально важны для пользователя.
