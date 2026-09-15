# Контрольная точка проекта — 15.09.2026 / STEP-46

## Рабочий HEAD

`e2b83eb42702971a7e5eb9fbbf7f1eea16b12ea6`

## Реальный дефект, найденный после STEP-45

При углублённом аудите `CriteriaStore.update()` обнаружено, что новый `TenderCriteria.__post_init__` проверял критерии только при создании объекта, но `CriteriaStore.update()` записывал изменения непосредственно в SQLite.

Следовательно, после STEP-45 всё ещё можно было сохранить логически невозможный профиль последовательностью обновлений, например:

1. сохранить `min_price=100, max_price=200`;
2. затем выполнить `update(min_price=300)`;
3. получить в базе `min_price=300, max_price=200`.

Это был реальный code-level дефект.

## Исправление

`CriteriaStore.update()` теперь:

1. загружает текущий профиль;
2. объединяет текущие значения с изменяемыми;
3. создаёт временный `TenderCriteria`;
4. выполняет всю валидацию;
5. только после успешной валидации записывает значения в SQLite.

Таким образом, противоречивое обновление не изменяет сохранённый профиль.

Дополнительно добавлена проверка конечности числовых значений через `math.isfinite()`, чтобы `NaN` и `Infinity` не могли попасть в критерии.

Добавлены regression tests:
- NaN/Infinity отвергаются;
- последовательное изменение диапазона не может сохранить противоречивое состояние;
- после rejected update старое корректное состояние сохраняется.

## Прогоны

Первый CI после исправления тестов дал failure #679. Причина была локализована и устранена: в новом тесте отсутствовали зависимости импорта `CriteriaStore/TenderDatabase`.

После исправления:

### CI

**Tender Intelligence Agent CI #680 — SUCCESS**

Фактический полный pytest:

**185 passed, 3 subtests passed**

Также успешно:
- unittest discovery;
- B2B parser;
- B2B reliable adapter;
- B2B quality gate;
- search pipeline regression;
- analytics;
- SQLite/Excel integration;
- Excel artifact verification;
- финальный CI quality gate.

### Linux browser

**Platform Browser Diagnostics #426 — SUCCESS**

Artifact validation и browser gate прошли.

### Windows browser

Для runtime-кода последняя полноценная проверка:

**Platform Browser Diagnostics (Windows) #15 — SUCCESS**

Она выполнена после commit `69a9047`, который содержал изменение runtime `src/telegram_settings.py`.

После этого изменялись только тесты и документация; runtime-код не менялся.

## Состояние

Все найденные в этом цикле внутренние дефекты исправлены и покрыты regression tests.

Известных оставленных code-level failures нет.

Внешняя доступность ЕИС/RTS/TMK из GitHub-hosted runners по-прежнему рассматривается отдельно: timeout/WAF классифицируются как внешнее ограничение, а не как пустой результат или внутренний успех.

## Постоянный алгоритм

Продолжать каждый цикл:

`HEAD/checkpoint → collectors → detail contract/normalization → filters/criteria → dedup/storage/notification fingerprints → AI/Ollama → Telegram/notifications → CRM → Excel → scheduler/orchestrator/CLI → полный CI → Linux browser → Windows browser при runtime-изменениях → artifact analysis`.

Любой failure:
- не объявлять GREEN;
- найти первопричину;
- исправить код;
- добавить regression test;
- повторить полный CI;
- повторить затронутые live/browser проверки;
- только затем создавать checkpoint.

## Итог STEP-46

**GREEN: code-level tests, full CI, Linux browser diagnostics, Windows runtime/browser validation.**

Полный pytest: **185 passed + 3 subtests passed**.
