# Контрольная точка — 2026-09-12 — STEP-24

## HEAD
`349ffdd937524a310c9bd534b3c9d7f7816cba8f`

## Исправление
Синхронизирован `SearchProfileStore` с расширенным `TenderCriteria`:
- `SearchProfile.criteria()` теперь переносит `exclusions` и `regions`;
- создание default profile больше не передаёт несовместимый `exclude_keywords` напрямую в `SearchProfile`;
- значения берутся явно и сохраняются в существующие profile columns `exclusions`/`regions`.

## Предыдущий CI
Run `34654537297`: 67 passed, 1 failed на profile migration. Ошибка зафиксирована в STEP-23.

## Следующий шаг
Проверить новый CI на HEAD `349ffdd...`. При любой ошибке — новый checkpoint перед исправлением. При зелёном CI продолжить customer INN, документы/ссылки и полноту detail-полей.

## Правило проекта
Каждая остановка фиксируется отдельным checkpoint независимо от результата.
