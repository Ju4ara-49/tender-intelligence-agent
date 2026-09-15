# Контрольная точка проекта — 15.09.2026 / STEP-44

## HEAD

Проверенный рабочий HEAD:

`1300e79de7a8a5c5dcc211fd81e50a37dcd10a58`

## Что исправлено после STEP-43

### 1. Фильтр регионов

Обнаружен реальный дефект в `Orchestrator._passes_regions`:

старый код использовал substring matching. Поэтому выбранный регион `Москва` мог ошибочно пропустить `Московская область`.

Исправлено:

- нормализация `г.` / `город`;
- нормализация `обл.` → `область`;
- нормализация `респ.` → `республика`;
- нормализация регистра/ё/разделителей;
- точное сравнение нормализованных регионов;
- поддержка тендера с несколькими регионами через `, ; | /`.

Добавлены regression tests:

- Москва не совпадает с Московской областью;
- `г. Санкт-Петербург` совпадает с `Санкт-Петербург`;
- `Ленинградская обл.` совпадает с `Ленинградская область`;
- пустой список фактических значений фильтра не отклоняет тендер;
- один из нескольких регионов тендера корректно совпадает с выбранным регионом.

### 2. Windows browser diagnostics

Workflow `.github/workflows/platform-browser-diagnostics-windows.yml` расширен:

`src/collectors/**` заменено на `src/**`.

Теперь изменения любого runtime-кода автоматически запускают Windows browser diagnostics, а не только изменения collectors.

## CI

**Tender Intelligence Agent CI #674 — SUCCESS**

HEAD: `1300e79d...`

Полный CI зелёный.

## Browser diagnostics

### Linux

**Platform Browser Diagnostics #420 — SUCCESS**

HEAD: `1300e79d...`

Внутренние browser diagnostic failures: 0.

### Windows

**Platform Browser Diagnostics (Windows) #13 — SUCCESS**

HEAD: `1300e79d...`

Внутренние browser diagnostic failures: 0.

Артефакты Linux и Windows сформированы.

Площадки, доступные из GitHub-hosted runner, проходят browser contract/live probe.

ЕИС, RTS-Tender и TMK могут оставаться внешне ограниченными GitHub runner сетью/WAF; это состояние не маскируется под пустой успешный поиск и отделено от code-level failures.

## Regression / test coverage

Последний полный CI подтвердил полный доступный test suite после изменения region filtering.

Кодовые изменения этого цикла не ослабляют проверки и не отключают тесты.

## Постоянный алгоритм

Продолжать по:

`актуальный HEAD → collectors/discovery → detail/normalization → filters → dedup/storage/notification fingerprints → AI/Ollama → Telegram/notifications → CRM → Excel → scheduler/orchestrator/CLI → CI → Linux browser → Windows browser`.

Для каждого найденного дефекта:

1. установить первопричину;
2. исправить код;
3. добавить regression test;
4. прогнать узкий тест;
5. прогнать полный CI;
6. прогнать browser diagnostics;
7. проверить фактический результат;
8. сохранить новый checkpoint.

Внешний timeout/WAF/access block никогда не превращать в false-green и никогда не выдавать за пустой результат площадки.

## Статус STEP-44

**GREEN по коду, тестам, CI, Linux browser diagnostics и Windows browser diagnostics.**

Внутренних известных дефектов, найденных в этом цикле и оставленных без исправления, нет.
