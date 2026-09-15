# STEP-49 — 15.09.2026

Контрольная точка сохранена после завершения текущего аудита scheduler/profile execution.

## HEAD

`c8595ba483abcc5699cd028176b383e9f3c2c4af`

Commit: `fix: deduplicate normalized scheduler profile users`

## Что исправлено с STEP-48

### Scheduler / multi-user execution
- Scheduler больше не ограничивается глобальным `orchestrator.run_cycle()` при наличии сохранённых включённых Telegram-профилей.
- Для каждого уникального нормализованного пользователя scheduler вызывает `run_cycle_for_user(user_id)`.
- Ошибка одного пользователя не останавливает выполнение остальных пользователей.
- При отсутствии включённых профилей сохранён backward-compatible fallback на глобальный `run_cycle()`.
- Учтён `stop_requested`.
- Реализована нормализация и Python-side deduplication user IDs после чтения из БД, включая варианты с пробелами.
- Логика совместима как с DB cursor через `fetchall()`, так и с list-like результатами, используемыми тестовыми doubles.

### Regression coverage
Добавлены/обновлены тесты scheduler для:
- регистрации и запуска;
- `run_on_start`;
- изоляции ошибок между пользователями;
- выполнения по включённым профилям;
- legacy fallback без профилей;
- валидации interval;
- дедупликации нормализованных user IDs.

## Проверки текущего HEAD

GitHub Actions check-runs для `c8595ba483abcc5699cd028176b383e9f3c2c4af`:

- `test` — SUCCESS.
- `browser-diagnostics` (Linux) — SUCCESS.
- `browser-diagnostics-windows` — SUCCESS.

Оба browser workflow завершились успешно на текущем HEAD. Внешние ограничения отдельных площадок (EIS/RTS/TMK: timeout/reset/WAF/JS+Cookies challenge) по-прежнему классифицируются как внешняя недоступность и не превращаются в ложный успешный пустой поиск.

## Состояние после checkpoint

- Scheduler/profile execution: исправлено и покрыто regression tests.
- CriteriaStore async user isolation: исправлено через `ContextVar`, regression test сохранён из STEP-48.
- Collector fail-closed: сохранён.
- Browser diagnostics false-green защита: сохранена.
- Rosatom published-listing fallback/parser: сохранён.
- Telegram profile routing / CRM callbacks / Telegram API `ok` validation: сохранены.
- Excel strict-result export и требуемая схема колонок: сохранены.
- CI и browser gates на текущем HEAD: GREEN.

## Следующий шаг

Продолжить полный аудит со следующего незакрытого слоя, не сбрасывая HEAD: collectors → detail/normalization → filters → dedup/storage/notification fingerprints → AI/Ollama → Telegram/CRM → Excel → scheduler/orchestrator/CLI → CI/Actions → live/browser diagnostics.

Не считать внешние timeout/WAF/CAPTCHA/access failures успешным пустым результатом. Любой новый внутренний дефект: root cause → code fix → regression test → full CI → затронутые live/browser checks → новый checkpoint.
