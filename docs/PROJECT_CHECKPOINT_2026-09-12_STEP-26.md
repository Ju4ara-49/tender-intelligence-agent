# Контрольная точка — 2026-09-12 — STEP-26

## HEAD
`5ca96d8b17e0add8993f62e78e273aaefafdb04f`

## Прогон после STEP-25
- CI #412 на `eaeff47`: **SUCCESS** — полный набор unit/pytest/B2B/search/analytics/Excel integration.
- Browser Diagnostics #207 на `eaeff47`: **SUCCESS** — реальный browser probe публичных порталов завершён успешно.
- После анализа browser-слоя обнаружена дополнительная зона риска: отправленный поиск, завершившийся нулём распарсенных процедур, должен диагностироваться явно.
- Усилен лог browser reliable collector: `RESULT_PARSER_ZERO`.
- Добавлен регрессионный тест browser detail на извлечение ИНН с пробелами.

## Текущий прогон
- CI #414 для текущего HEAD: queued.
- Browser Diagnostics #209 для текущего HEAD: queued.
- CI #413 / Browser #208 для предыдущего `b7516f1` ещё выполняются.

## Правило
После каждого завершённого прогона создаётся отдельный checkpoint. Даже неуспешный прогон фиксируется с причиной.
