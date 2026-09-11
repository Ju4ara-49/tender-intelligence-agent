# Контрольная точка — 2026-09-11 — STEP-04

HEAD: `7c3c0c5fb4280a030900dbeaf2dc1ab0013845ca`

## Исправлено
Добавлен `src/storage/notification_delivery.py` — отдельный слой rich event fingerprint.

Fingerprint теперь учитывает:
- title/url;
- price/currency;
- start/end/deadline/published_at;
- region/customer/law;
- advance required/percent;
- postpayment days;
- application security;
- contract security.

Orchestrator переведён с `db.was_notified()` на этот слой. Старые `notifications` не ломаются: сервис умеет один раз поднять legacy notification в новый event baseline.

## Тест
Добавлен `tests/test_notification_delivery_state.py`, проверяющий повторяемость fingerprint и реакцию на изменение цены/payment.

## Проверка CI
GitHub Actions для предыдущей контрольной точки `f25c01e...` завершился успешно: все существующие deterministic/search/analytics/Excel тесты прошли.

## Следующий шаг
Провести отдельный аудит всех шести collectors и их обязательных полей, начиная с B2B/Fabrikant/RTS/TMK/Rosatom и затем EIS.
