# Контрольная точка — 2026-09-12 — STEP-28

## Зафиксированный завершённый прогон

### CI #417
- HEAD: `6715b8edf4558dda9fca3e097e9617d140ef57e4`
- результат: **SUCCESS**
- полный CI после исправления browser customer INN прошёл.

### Browser Diagnostics #212
- HEAD: `6715b8edf4558dda9fca3e097e9617d140ef57e4`
- результат: **SUCCESS**, но старый diagnostics покрывал только RTS-Tender, TMK и Rosatom.

## Обнаруженный недостаток диагностики
Статус SUCCESS нельзя было трактовать как проверку всех поддерживаемых площадок: `ALL_COLLECTORS` содержит EIS, B2B-Center, Fabrikant, RTS-Tender, TMK и Rosatom, а browser diagnostics проверял только три последние.

## Исправления после аудита
- расширен `tests/platform_browser_diagnostics.py`:
  - EIS;
  - B2B-Center;
  - Fabrikant 223;
  - Fabrikant 44;
  - RTS-Tender;
  - TMK;
  - Rosatom;
- diagnostics теперь считает WAF/block ошибкой, а не успешным результатом;
- workflow увеличен до 15 минут;
- `continue-on-error: true` удалён: browser diagnostics теперь является реальным CI gate;
- добавлена расширенная проверка search surface и наличия результатов.

## Новый HEAD
`db83b41f0780a1c2a15bd2d17c6bca3b88ebcd0a`

## Новые прогоны
- CI #419 — queued.
- Platform Browser Diagnostics для нового HEAD — queued.

## Следующий обязательный шаг
Дождаться результатов обоих новых прогонов. Для browser diagnostics отдельно разобрать каждый из 7 endpoint-проверок. Если хотя бы один endpoint не проходит — исправлять соответствующий collector/diagnostics и запускать новый цикл. После каждого завершённого прогона создавать следующий checkpoint.
