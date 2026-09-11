# Контрольная точка — 2026-09-12 — STEP-23

## HEAD при обнаружении
`2bcad72c2377444f7fab3500ecc5b3b18e253074`

## CI
Run `34654537297` завершился ошибкой полного pytest: **67 passed, 1 failed**.

Падает `tests/test_search_profiles.py::test_default_profile_migrates_real_criteria`.

## Причина
`TenderCriteria` был расширен полями `exclude_keywords` и `regions`, а `SearchProfileStore.ensure_default_profile()` передаёт `asdict(criteria)` напрямую в `SearchProfile(...)`. `SearchProfile` пока не содержит эти два поля, поэтому возникает `TypeError: unexpected keyword argument 'exclude_keywords'`.

## Следующий шаг
Синхронизировать `SearchProfile` с расширенным `TenderCriteria`: добавить `exclude_keywords` и `regions`, включить их в SQLite schema/CRUD и в `criteria()` conversion. Затем полный CI. После зелёного результата продолжить customer INN/documents/detail audit.

## Правило проекта
Перед каждой остановкой обязательно сохранять отдельный checkpoint независимо от результата.
