# Контрольная точка — 2026-09-12 — STEP-17

## Состояние остановки
Работа остановлена для фиксации состояния независимо от результата CI, согласно правилу проекта.

## CI
Последний полный CI для commit `a948770c257356f1c2efd8d154d84a136a3fe18a` завершился ошибкой: `54 passed, 1 failed`.
Падает новый регрессионный тест `tests/test_notification_delivery.py::test_legacy_notification_does_not_hide_changed_tender`.

## Причина
`NotificationDeliveryState.was_notified()` при отсутствии совпадающего event fingerprint и наличии legacy-записи `notifications` создаёт событие для ТЕКУЩЕГО состояния и возвращает `True`. Это ошибочно: после изменения цены текущий fingerprint должен считаться новым событием.

При этом миграция `TenderDatabase._migrate_legacy_notifications()` уже переносит legacy-записи в `notification_events` на момент инициализации БД. Дополнительный fallback в `NotificationDeliveryState.was_notified()` не нужен и маскирует изменения.

## Следующий шаг
Удалить legacy fallback из `NotificationDeliveryState.was_notified()`, сохранить регрессионный тест и запустить полный CI. После результата — снова создать checkpoint и продолжить углублённый аудит БД, всех 6 коллекторов, фильтров и Excel.
