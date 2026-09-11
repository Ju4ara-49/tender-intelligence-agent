# Контрольная точка — 2026-09-11 — STEP-01

## Проверка после предыдущих изменений

HEAD на момент продолжения: `a7c8eec` (`add browser collector field contract regression test`).

Проверено:
- `src/orchestrator.py` — порядок pipeline: discovery → soft keyword filter → details enrichment → strict keyword filter → region/criteria → DB save → AI → Telegram.
- `src/storage/database.py` — добавлена event-модель уведомлений `notification_events`; legacy `notifications` сохранена для совместимости.
- `src/models/tender.py` — модель содержит `start_date`, `end_date`, `advance_required`, `advance_percent`, `postpayment_days`, application/contract security.
- `src/telegram_settings.py` — критерии пользователя поддерживают price, advance, postpayment, сроки подачи и security.

## Найденные проблемы для следующего шага
1. `Orchestrator._enrich_tender()` переносит из detail-объекта не все поля модели Tender: отсутствуют прямые переносы `start_date`, `end_date`, `advance_required`, `advance_percent`, `postpayment_days`, `application_security_percent`, `contract_security_percent`.
2. Фильтры `max_postpayment_days`, `max_application_security_percent`, `max_contract_security_percent` используют `or 0`, поэтому неизвестное значение ошибочно трактуется как нулевое и может пройти ограничение.
3. SQLite `tenders` пока не имеет отдельных колонок `start_date`/`end_date`; эти значения существуют в модели, но не являются частью основного persisted contract.
4. Fingerprint уведомления пока не включает advance/payment/security/start/end date, поэтому изменение только этих параметров не создаёт новое событие уведомления.
5. Для commit `a7c8eec` GitHub connector не вернул workflow runs/status checks; автоматический CI этим интерфейсом не подтверждён.

## Следующее действие
Исправить enrichment и строгую семантику критериев, затем добавить регрессионные тесты и сохранить отдельную контрольную точку.
