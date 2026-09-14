# Контрольная точка проекта — 13.09.2026

## Последний проверенный код

`58641e983ab0240169e8005e43a1712ab69c9d69`

Последующий docs-only commit обновляет только эту контрольную точку и не меняет проверенный код.

Последние изменения этого цикла:

1. `3b8b645` — CRM Telegram workflow coverage.
2. `1f6db46` — harden CRM Telegram status transitions.
3. `cf06c18` — tests for Russian CRM status aliases.
4. `b4b851a` — deterministic CRM status keyboard order.
5. `c327846` — полноценный Telegram UI для CRUD профилей поиска: создание, просмотр, редактирование, включение/выключение, дублирование и удаление.
6. `58641e9` — регрессионные тесты Telegram UI профилей и ограничений callback payload.

## CI — GREEN

GitHub Actions `Tender Intelligence Agent CI`, run **#570**, для кода `58641e9` завершён успешно.

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

Результат: **0 внутренних CI failures**.

## Browser diagnostics — GREEN по внутренней диагностике

Browser diagnostics run **#316**, код `58641e9`, завершён успешно.

Результаты артефакта:

- B2B-Center — `ok`;
- Фабрикант 223 — `ok`;
- Фабрикант 44 — `ok`;
- Росатом — `ok`;
- ЕИС — `external_timeout`;
- РТС-тендер — `external_timeout`;
- ТМК — `external_timeout`;
- `ci_failures = []`;
- `access_blocks` содержат только три внешних timeout.

Следовательно, browser diagnostics не обнаружил ни одного внутреннего parser/adapter/CI failure. Три портала не дали доказательство из GitHub-hosted Chromium из-за внешнего transport/navigation timeout; это не преобразовано в ложный `ok` и отдельно зафиксировано как внешнее ограничение.

## Telegram «Ключи»

Полноценный CRUD UI доступен в production-классе `FullCriteriaTelegramBot`:

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

## Алгоритм продолжения работы

При следующем продолжении не начинать аудит заново. Работать циклом:

`HEAD/checkpoint → слой → тест → полный CI → browser diagnostics → анализ артефактов → исправление → регрессионный тест → повторный полный прогон`.

Порядок слоёв:

`collectors → detail contract → filters/criteria → dedup/storage/notification delivery → AI → Telegram → CRM → Excel → scheduler → Windows/runtime → CI/Actions`.

Правило остановки: **не останавливаться на формулировке «работа не завершена»**. Если прямой путь проверки заблокирован внешней системой, переходить к альтернативному воспроизводимому тесту, fixture/contract test, browser-проверке доступной части или другому способу доказательства. Реальный внутренний test/CI failure обязан быть устранён и перепроверен до следующего слоя.

Внешние timeout/WAF/ограничения GitHub-hosted runner фиксировать отдельно и не маскировать их под успешный сбор данных.


## Дополнительный цикл проверки — 23:38 MSK

После контрольной точки был найден и исправлен функциональный дефект многопрофильной доставки: уведомления были scoped по profile ID, из-за чего один пользователь мог получать один тендер несколько раз при совпадении нескольких профилей. Исправление перевело recipient scope на пользователя и добавило агрегацию уникальных результатов между профилями. Добавлен regression test.

Исправляющий commit: `00e72a5aa459d4239d53f94c168cc75780d06160`.

CI run **#572** на этом commit — **SUCCESS**, все 39 шагов job завершены успешно, включая полный pytest и SQLite/Excel integration.

Browser diagnostics run **#318** на том же commit — **SUCCESS**. Внутренних диагностических failures нет. Реально доступны и подтверждены browser-проверкой B2B-Center, Фабрикант 223/44 и Росатом. ЕИС, РТС-Тендер и ТМК классифицированы как внешние network/navigation timeout, а не как ошибки Python/парсеров.

Артефакт browser diagnostics дополнительно разобран вручную: `ci_failures=[]`; для доступных площадок получены HTTP 200 и реальные страницы результатов. Для Фабриканта 223 диагностический result count = 0, что не считается ошибкой: страница доступна, search control обработан, а отсутствие найденных процедур является валидным результатом данного публичного запроса.

Следующее продолжение начинать с commit `00e72a5aa459d4239d53f94c168cc75780d06160`, не откатывая исправление многопрофильной доставки.


## Validation cycle 14.09.2026 — numeric profile hardening

Продолжен цикл до полного зелёного результата. SearchProfileStore дополнительно защищён от отрицательных и нечисловых/бесконечных значений для числовых критериев профиля через finite/non-negative validation. Добавлен regression test для отрицательной цены, NaN аванса и AI score вне диапазона.

Validation: commit 249be34e7e745f7c9c57985ae443c10be5a42901; CI #580 SUCCESS. Browser diagnostics #326 SUCCESS на том же commit. Артефакт diagnostics разобран: ci_failures=[]; B2B-Center, Фабрикант 223/44 и Росатом проходят browser probe; ЕИС, РТС-Тендер и ТМК остаются внешне недоступными на GitHub-hosted runner и классифицированы как external_timeout, а не как внутренний failure.

Важно: browser diagnostics не объявляет внешние timeout успехом. Для 100% live-подтверждения этих трёх площадок требуется runner/network, из которого они реально доступны. Web-доступ отдельно подтвердил, что TMK отвечает JS/Cookie challenge, а ЕИС также не проходит внешний fetch; это подтверждает внешний характер ограничения, но не заменяет production browser probe.

Следующая контрольная точка: 249be34e7e745f7c9c57985ae443c10be5a42901.


## Validation cycle 14.09.2026 — CRM convergence + browser diagnostics hardening

Контрольная точка обновлена после обнаружения реального CI-дефекта: в репозитории существовали две расходящиеся реализации TenderBoard — старая в src/storage и новая в src/crm/board. Тесты импортировали старую реализацию, из-за чего case-insensitive labels и unassign были фактически не доступны тестируемому API. Исправлено: каноническая реализация теперь находится в src/storage, src/crm/board является совместимым re-export, добавлены persistent history, нормализация/уникальность label_key и миграция старой схемы.

Добавлены regression tests на идентичность обоих import paths и миграцию legacy label schema.

CI #592 — SUCCESS на commit 94ef517442a92408c9827bd3fac3c4395118c831.

Browser diagnostics #338 — SUCCESS на том же commit; ci_failures=[]. На реальном browser probe B2B-Center, Фабрикант 223/44 и Росатом дали HTTP 200 и реальные result/link evidence. ЕИС, RTS-Tender и TMK дали external_timeout; это классифицировано как external_access, не Python failure.

Дополнительно устранён флап diagnostics Росатома: legacy published-procurement page иногда не содержит поискового control, но содержит реальные официальные procedure links. Такой ответ теперь классифицируется как listing_available/published_listing_fallback, а не ложный search_adapter CI failure. Это не маскирует WAF/HTTP blocks и не объявляет отсутствие поиска полноценным search success.

Алгоритм на будущее закреплён: 1) фиксировать commit/checkpoint; 2) аудит collectors → detail contract/normalization → filters → dedup/storage/notification → AI/Ollama → Telegram/CRM → Excel → orchestrator/scheduler → CI → browser/live diagnostics; 3) каждый найденный внутренний дефект исправлять в коде; 4) добавлять regression test; 5) повторять полный CI; 6) разбирать фактический diagnostic artifact, а не только статус workflow; 7) внешние timeout/WAF не маскировать под success; 8) при флапах диагностики улучшать классификацию и повторять полный прогон до GREEN.

Следующая контрольная точка: 94ef517442a92408c9827bd3fac3c4395118c831.
