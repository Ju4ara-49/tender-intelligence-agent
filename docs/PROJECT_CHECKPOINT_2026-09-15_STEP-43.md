# Контрольная точка проекта — 15.09.2026 / STEP-43

## Проверенный код

Последний проверенный кодовый HEAD:

`0845971d374ae7ec7004fef7209e05bdf44312c8`

Цепочка исправлений этого цикла:

- `ed867b6` — runner-aware browser diagnostic policy;
- `5a2929b` — browser artifact gate reads internal failures separately;
- `056c2a7` — Linux browser diagnostics records external runner limits as non-blocking;
- `d943dd4` — Windows browser diagnostics added as a separate Windows runtime;
- `91be070` — regression coverage for browser gate;
- `988304b` — TMK JavaScript/cookie challenge classification + Windows UTF-8 stdout;
- `49f86b4` — diagnostic summary metadata fix;
- `8a9a2eb` — regression coverage for summary metadata;
- `6527677` — classify TMK WAF response as external access;
- `1993ae2` — regression test for TMK WAF marker;
- `0845971` — Windows diagnostic workflow records external network limitations without treating them as Python/parser failures.

## CI — GREEN

GitHub Actions **Tender Intelligence Agent CI #668** — SUCCESS.

Фактические результаты:

- unittest discovery: **60 tests — OK**;
- дополнительный unittest suite: **5 tests — OK**;
- B2B reliable adapter: **2 tests — OK**;
- B2B quality gate: **4 tests — OK**;
- полный pytest: **175 passed, 3 subtests passed**;
- search pipeline regression: **6 passed**;
- analytics: **1 passed**;
- SQLite/Excel integration: SUCCESS;
- Excel artifact: SUCCESS;
- test SQLite artifact: SUCCESS;
- финальный CI quality gate: SUCCESS.

## Browser diagnostics — GREEN

Linux browser diagnostics **#414** — SUCCESS.

Windows browser diagnostics **#12** — SUCCESS.

В обоих прогонах:

- B2B-Center — HTTP 200, **23 359** результатов;
- Фабрикант 223 — HTTP 200, валидный результат **0**;
- Фабрикант 44 — HTTP 200, **13** результатов;
- Росатом — HTTP 200, **10** результатов;
- внутренних browser diagnostic failures — **0**;
- все обязательные screenshots/report/summary artifacts сформированы;
- artifact gate — PASS.

ЕИС, RTS-Tender и TMK в GitHub-hosted runners остаются недоступными для полноценного live browser probe:

- ЕИС — external navigation timeout;
- RTS-Tender — external navigation timeout;
- TMK — external JavaScript/cookie/WAF challenge либо navigation timeout.

Это записывается в `access_blocks` и `ci_failures`, но при `HARD_EXTERNAL_ACCESS=0` не маскируется как успешный результат: состояние остаётся `external_timeout` / `external_challenge`. Внутренний parser/adapter failure при этом остаётся блокирующим и приводит к CI failure.

## Исправленные реальные дефекты этого цикла

1. Windows runner падал на Unicode JSON в stdout из-за CP1252. Исправлено принудительным UTF-8 stdout с `errors="replace"`.
2. Добавленные поля диагностического отчёта попадали в цикл формирования summary как будто это platform entries. Исправлено.
3. TMK HTTP 500/WAF page раньше ошибочно классифицировалась как `search_control_missing`. Теперь она классифицируется как `external_challenge` / `external_access`.
4. Browser gate теперь разделяет внутренние дефекты кода и внешние ограничения runner/network.
5. Добавлен отдельный Windows browser workflow, чтобы Linux runner не был единственной средой проверки.

## Постоянный алгоритм продолжения

Каждый следующий цикл обязан начинаться с актуального HEAD и последнего checkpoint и проходить:

`HEAD/checkpoint → collectors → detail contract/normalization → filters/criteria → dedup/storage/notification delivery → AI/Ollama → Telegram → CRM → Excel → orchestrator/scheduler → Windows/runtime → CI → browser/live diagnostics`.

Для каждого найденного внутреннего дефекта:

1. определить первопричину;
2. исправить код;
3. добавить regression test;
4. выполнить релевантный тест;
5. выполнить полный CI;
6. разобрать фактический browser artifact;
7. повторить цикл до GREEN.

Внешние timeout/WAF/runner ограничения не объявлять успехом и не маскировать под данные площадки. Если внешний сервис блокирует GitHub-hosted runner, сохранять это как отдельное доказанное состояние и использовать альтернативную воспроизводимую проверку: другой runner/ОС, доступный endpoint, fixture/contract test или локальный runtime probe.

После каждого полного цикла создавать отдельный checkpoint с HEAD, результатами, найденными дефектами, исправлениями и оставшимися внешними ограничениями.

## Итог STEP-43

Кодовый и CI-контур на HEAD `0845971d374ae7ec7004fef7209e05bdf44312c8` — GREEN.

Никаких известных внутренних тестовых или browser-diagnostic дефектов на этом HEAD не осталось.
