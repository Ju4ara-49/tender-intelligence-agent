# Контрольная точка проекта — 13.09.2026

## Текущий HEAD

`b4b851a387de3988086c6f2a944d782508943600`

Последние изменения этого цикла:

1. `3b8b645` — CRM Telegram workflow coverage.
2. `1f6db46` — harden CRM Telegram status transitions.
3. `cf06c18` — tests for Russian CRM status aliases.
4. `b4b851a` — deterministic CRM status keyboard order.

## Результат проверки кода

GitHub Actions `Tender Intelligence Agent CI`, run #567, для `b4b851a` завершён успешно.

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
- финальный CI quality gate.

## CRM

CRM-доска теперь имеет полноценный Telegram adapter:

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

Browser diagnostics run #314 завершён успешно. B2B-Center, Фабрикант (223/44) и Росатом дали положительное внешнее browser-доказательство. ЕИС, РТС-тендер и ТМК из GitHub-hosted runner получили `external_timeout`; это классифицировано как внешняя доступность окружения, не как Python/CI failure. `ci_failures` = 0.

## Алгоритм продолжения работы

При следующем продолжении не начинать аудит заново. Работать циклом:

`HEAD/checkpoint → слой → тест → полный CI → browser diagnostics → анализ артефактов → исправление → регрессионный тест → повторный полный прогон`.

Порядок слоёв:

`collectors → detail contract → filters/criteria → dedup/storage/notification delivery → AI → Telegram → CRM → Excel → scheduler → Windows/runtime → CI/Actions`.

Не объявлять новый слой готовым при наличии реального внутреннего тестового падения. Внешние timeout/WAF/ограничения GitHub-hosted runner фиксировать отдельно и проверять альтернативным доступным способом, не маскируя их под успешный сбор данных.
