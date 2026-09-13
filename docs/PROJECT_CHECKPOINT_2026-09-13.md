# Контрольная точка проекта — 13.09.2026

## Текущий HEAD

`58641e983ab0240169e8005e43a1712ab69c9d69`

Контрольная точка зафиксирована после реализации Telegram CRUD UI для сохранённых профилей поиска (`Ключи`).

Последние изменения этого цикла:

1. `3b8b645` — CRM Telegram workflow coverage.
2. `1f6db46` — harden CRM Telegram status transitions.
3. `cf06c18` — tests for Russian CRM status aliases.
4. `b4b851a` — deterministic CRM status keyboard order.
5. `f884e52` — полноценный Telegram UI для CRUD профилей поиска: создание, просмотр, редактирование, включение/выключение, дублирование и удаление.
6. `58641e9` — регрессионные тесты Telegram UI профилей и ограничений callback payload.

## Результат проверки кода

GitHub Actions `Tender Intelligence Agent CI`, run #570, для `58641e9` завершён успешно.

Успешно завершены все обязательные этапы:

- unittest discovery;
- B2B parser tests;
- B2B reliable adapter tests;
- B2B quality gate;
- полный `pytest`;
- search pipeline regression;
- analytics;
- SQLite + Excel integration;
- проверка Excel artifact;
- загрузка test SQLite artifact;
- финальный CI quality gate.

Отдельно добавлены regression tests для Telegram `Ключи`: keyboard, CRUD callback routing и ограничение длины Telegram callback payload.

## Telegram «Ключи»

Полноценный CRUD UI теперь доступен в production-классе `FullCriteriaTelegramBot`:

- `Ключи` открывает список профилей пользователя;
- создание нового профиля копирует текущие критерии пользователя;
- просмотр профиля показывает фактические настройки и статистику запусков;
- редактирование поддерживает название, ключевые слова, исключения, площадки, регионы, цены, аванс, постоплату, обеспечение заявки/контракта, срок и AI-балл;
- включение/выключение управляет тем, какие профили участвуют в `run_cycle_for_user`;
- дублирование и удаление доступны из карточки профиля;
- значения пользователя HTML-экранируются;
- доступ к профилям всегда ограничен текущим `chat_id` через `SearchProfileStore`;
- callback payloads проверяются regression-тестами.

## CRM

CRM-доска имеет полноценный Telegram adapter:

- кнопка `CRM тендера` в полном Telegram UI;
- `/tender ID` и `/crm ID`;
- `/crm_status ID STATUS` и `/статус_тендера`;
- `/assign ID ФИО`;
- `/label ID метка`;
- inline-переходы статуса;
- HTML escaping пользовательских значений;
- русские названия статусов принимаются как команды;
- inline-кнопки показывают только допустимые переходы state machine;
- порядок кнопок стабилен и соответствует `ALL_STATUSES`;
- тесты CRM покрывают карточку, переходы, русские статусы, ответственного, метки и валидацию ID.

## Платформы

Реестр содержит ровно шесть поддерживаемых площадок:

- ЕИС;
- B2B-Center;
- Фабрикант;
- РТС-тендер;
- ТМК;
- Росатом.

`UniPro` отсутствует.

Browser diagnostics для текущего кода выполняется отдельным workflow run #315. Предыдущий run #314 дал положительное внешнее browser-доказательство для B2B-Center, Фабриканта (223/44) и Росатома; ЕИС, РТС-тендер и ТМК получили `external_timeout`, классифицированный как внешнее ограничение GitHub-hosted окружения, при `ci_failures = 0`.

## Алгоритм продолжения работы

При следующем продолжении не начинать аудит заново. Работать циклом:

`HEAD/checkpoint → слой → тест → полный CI → browser diagnostics → анализ артефактов → исправление → регрессионный тест → повторный полный прогон`.

Порядок слоёв:

`collectors → detail contract → filters/criteria → dedup/storage/notification delivery → AI → Telegram → CRM → Excel → scheduler → Windows/runtime → CI/Actions`.

Правило остановки: **не останавливаться на формулировке «работа не завершена»**. Если прямой путь проверки заблокирован внешней системой, переходить к альтернативному воспроизводимому тесту, fixture/contract test, browser-проверке доступной части или другому способу доказательства. Реальный внутренний тестовый failure обязан быть устранён и перепроверен до следующего слоя.

Внешние timeout/WAF/ограничения GitHub-hosted runner фиксировать отдельно и не маскировать их под успешный сбор данных.
