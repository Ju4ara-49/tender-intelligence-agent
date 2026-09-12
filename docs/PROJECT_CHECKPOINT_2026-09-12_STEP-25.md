# Контрольная точка — 2026-09-12 — STEP-25

## HEAD
`f1c37dd92c040c63af8a274312e11f6ffdbad051`

## Исправления
- Усилено извлечение ИНН в общем detail contract: поддерживаются пробелы между цифрами, при этом сохраняются ограничения на 10/12 цифр.
- Detail-only `documents` и `field_sources` теперь сохраняются в `raw_data`, чтобы не теряться при SQLite JSON round-trip.
- `Tender.__post_init__` восстанавливает `documents` и `field_sources` из `raw_data` для совместимости со старыми объектами/БД.
- Добавлены регрессионные тесты на round-trip метаданных и ИНН с пробелами.

## Проверки
- CI run `34693872386` (Tender Intelligence Agent CI) на HEAD: все тестовые шаги завершены успешно, включая unittest, B2B parser/reliable/quality, полный pytest, search pipeline, analytics и Excel integration.
- Platform Browser Diagnostics run `34693872432` на HEAD: на момент checkpoint выполняет реальный probe public tender portals; результат ещё не зафиксирован.

## Следующий глубокий блок
После завершения browser diagnostics продолжить аудит полноты detail-полей по всем платформам, прежде всего customer/ИНН, документы/ссылки, даты, способ закупки и коммерческие условия, затем проверить соответствие Telegram-фильтров и Excel/SQLite round-trip.

## Правило проекта
Каждая остановка фиксируется отдельным checkpoint независимо от результата.
