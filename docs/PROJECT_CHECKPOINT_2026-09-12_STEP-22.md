# Контрольная точка — 2026-09-12 — STEP-22

## HEAD
`e8ebdee81941bc59ad6db2bc6915ea74e2616c23`

## Что сделано
- Добавлен `ReliableEisZakupkiCollector`, который после штатной загрузки деталей ЕИС выполняет финальный разбор коммерческих условий через существующий EIS parser.
- Унифицированы поля: `advance_required`, `advance_percent`, `postpayment_days`, `application_security_percent`, `contract_security_percent`.
- Реальный registry переключён на новый EIS adapter.
- Добавлен регрессионный тест `tests/test_eis_commercial_adapter.py`.
- Предыдущие блоки по SQLite датам, notification events и Telegram критериям сохранены.

## CI
После commit `e8ebdee81941bc59ad6db2bc6915ea74e2616c23` автоматически запущен CI. Результат на момент checkpoint ещё не проверен.

## Следующий шаг
Проверить CI. При ошибке: checkpoint → исправление → CI. При успехе: аудит customer INN, документов/ссылок и полноты detail-полей всех шести платформ.

## Правило проекта
Каждая остановка независимо от результата фиксируется отдельным checkpoint.
