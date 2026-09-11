# Контрольная точка — 2026-09-11 — STEP-02

HEAD: `0913919996dd99ee06c3bf8b672191691a114f68`

## Исправлено
- `Orchestrator._normalize_tender_datetimes()` теперь нормализует `start_date` и `end_date` и использует `end_date` как fallback для `deadline`.
- `Orchestrator._enrich_tender()` переносит из detail-объекта все ключевые поля Tender: start/end date, advance, postpayment и обе security.
- `max_postpayment_days` теперь отклоняет неизвестное значение вместо трактовки `None` как `0`.
- `max_application_security_percent` и `max_contract_security_percent` теперь также отклоняют неизвестные значения вместо ложного прохождения фильтра.

## Контракт
Это устраняет ситуацию, когда явно заданное ограничение пользователя фактически обходилось из-за отсутствующего значения на конкретной площадке.

## Следующий шаг
Добавить regression tests для enrichment и всех граничных случаев критериев; затем сохранить следующую контрольную точку.
