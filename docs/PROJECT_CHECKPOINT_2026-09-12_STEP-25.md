# Контрольная точка — 2026-09-12 — STEP-25

## Базовый HEAD
`7285232997d10653cc046a22012dcae403b1c3fc` (STEP-24, зелёный CI).

## Исправлено

### 1. Fabrikant: дата публикации без времени съезжала на день назад
`FabrikantV3Collector._parse_human_date` подставляла `00:00` при отсутствии времени.
Исправлено: default noon (12:00) для date-only значений.

### 2. Tender: пост-конструкторное присвоение дат обходило UTC-нормализацию
Добавлен `Tender.to_utc()`; `fabrikant_v3.get_details` вызывает его явно.

### 3. Windows log rotation WinError 32
`SafeRotatingFileHandler` в `src/logging_utils.py` — rollover не падает при блокировке файла.

## Тесты
- `test_fabrikant_v3_date_only_publication_date_keeps_calendar_day`
- `test_logging_utils.py::test_safe_rotating_handler_survives_permission_error_on_rollover`
- Полный CI локально: 70 pytest + unittest + Excel integration — зелёный.

## Следующий шаг
Фикстуры для customer INN / documents на площадках; B2B `law_type` / `start_date`.
