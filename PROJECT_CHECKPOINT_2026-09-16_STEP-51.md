# STEP-51 — 16.09.2026

## Контрольная точка
HEAD `main` на момент прогона: `0c1b38ce7f668c5b59fdbd4a81d073ff63974f22`
("claude_16.09.2026" — см. раздел "Обнаруженная проблема процесса" ниже).
Код изменён поверх этого коммита, **не смёржен** — применяется через GitHub
web UI (см. `PATCHES/` в приложенном архиве).

## Обнаруженная проблема процесса (важно прочитать в первую очередь)
Коммит `0c1b38c "claude_16.09.2026"` не является применённым патчем — это
**сырой ZIP-файл**, загруженный как бинарный артефакт в корень репозитория.
Внутри него лежали исправленный `b2b_center.py`, тест, `.patch` и checkpoint
STEP-50, подготовленные в прошлом цикле, но так и не применённые к реальному
коду. Из-за этого CI на `main` в текущем виде **не проходит** — `test_b2b_parser.py`
падает (2 из 5 тестов). Ниже это устранено вместе с более широким аудитом.

Также подтверждено (без изменений в git, только диагностика): ветка
`integration/crm-board-layer` (ранее считавшаяся "PR #7, ожидает мерджа")
на самом деле разошлась с `main` 216 коммитов назад против 90 у себя самой —
это устаревшая линия разработки, **её нельзя мерджить** в `main`, так как
`main` уже содержит собственную, более полную реализацию CRM/Telegram-слоя.

## Среда выполнения
Песочница имеет egress allowlist без доступа к zakupki.gov.ru, b2b-center.ru,
rts-tender.ru, fabrikant.ru, tmk и rosatom-доменам. Выполнены: полный
статический аудит кода, полный CI-эквивалентный прогон тестов на
детерминированных fixtures, точечные исправления найденных дефектов.
Live/browser diagnostics против реальных площадок физически недоступны из
этой среды — не выдаются за пройденную проверку.

## Найденные и исправленные дефекты

### 1. B2B-Center — неполный словарь морфологии (было в неприменённом ZIP)
`src/collectors/b2b_center.py::_keyword_matches_tender` не содержал форм
`подшипник`/`лебедка` и искал варианты по точному ключу словаря, а не по
членству словоформы в группе. Из-за этого запрос в словоформе, отличной от
именительного единственного (`подшипники`), не находил совпадений вовсе.
**Исправлено**: переход на поиск по членству в группе форм.
Regression-тест: `test_keyword_relevance_covers_required_smoke_keywords`.

### 2. Тот же класс бага — ещё в 3 независимых модулях
Обнаружено при целевом grep по всем сборщикам после фикса №1 (памятка из
STEP-50: "4 дублирующихся словаря морфологии — единая точка отказа"):

- `src/collectors/tenderguru_fallback.py` — **серьёзнее**: `TOPIC_URLS.get(keyword)`
  и `VARIANTS.get(query, (query,))` ключированы точной формой. При словоформе,
  отличной от ключа, `TOPIC_URLS.get()` возвращал `None` → `search()` молча
  возвращал `[]` **без единого HTTP-запроса**, маскируясь под "нет результатов"
  вместо явной ошибки.
- `src/collectors/browser_public_reliable.py::ReliableBrowserSearchMixin._tender_matches_query`
- `src/collectors/browser_public.py::_BrowserTenderCollector._tender_matches_query`
  (влияет на RTS-Tender, TMK, Rosatom, Fabrikant-fallback)

**Исправлено** во всех трёх: резолвинг словоформы запроса к канонической
форме через членство в группе, до обращения к словарю.
Regression-тесты: `test_tenderguru_fallback.py` (+2 теста),
`test_browser_public_parser.py` (+2 теста).

### 3. EIS — `NameError` в основном пути поиска (критично, было незамечено)
`src/collectors/eis_reliable.py::_search_rss` использует `urljoin(BASE_URL, link)`,
но `BASE_URL` не был импортирован из `eis_zakupki` (импортировались только
`EisZakupkiCollector, SEARCH_URL`). Любой реальный RSS-результат со ссылкой
вызывал `NameError`, который блок `except Exception` в `search()` тихо
проглатывал как "сбой RSS", из-за чего EIS **всегда** откатывался на
degraded-пути (tenderguru fallback / сырой HTML-пробник), даже когда RSS
работал штатно. Это не было покрыто ни одним тестом.
**Исправлено**: `BASE_URL` добавлен в импорт.
Regression-тест: `test_search_rss_resolves_relative_link_without_nameerror`.

### 4. Fabrikant V3 — обход UTC-нормализации при обогащении деталей
`src/collectors/fabrikant_v3.py::get_details` присваивал `published_at`/
`start_date` напрямую на уже сконструированный `Tender`, минуя
`Tender.__post_init__` (который нормализует таймзону только при
конструировании). Тот же класс бага, что был найден и исправлен ранее в
`_parse_human_date`/`_parse_datetime` (STEP до этого цикла), но в другом
месте того же коллектора.
**Исправлено**: явный вызов `detailed.to_utc()` после присвоения.
Regression-тест: `test_get_details_normalizes_recovered_publication_date_to_utc`
(проверен на реальное падение без фикса, затем на прохождение с фиксом).

### 5. Мелкое: `browser_public_reliable.py` — `Tender` в аннотации типа без импорта
Не вызывало падений благодаря `from __future__ import annotations`
(отложенные аннотации), но `pyflakes` пометил как `undefined name`.
Добавлен явный импорт для защиты от будущих поломок (например, если
что-то в проекте начнёт использовать `typing.get_type_hints`).

## Статический анализ (pyflakes) — весь проект
Прогнан `python -m pyflakes .` по всему репозиторию. Кроме уже исправленного:

- `src/collectors/eis_zakupki.py:1235` — дублирующееся определение
  `_extract_customer_from_soup` (первая версия на строке 1118 — мёртвый код,
  Python использует вторую, более полную). **Не исправлено** — поведение
  уже корректно (вторая версия побеждает), риск правки не оправдан в этом
  цикле; первая версия помечена на удаление как техдолг.
- `src/collectors/fabrikant.py` (не `_v2`/`_v3`) — дублирующийся
  `_parse_results`, но сам файл **не используется** ни одним активным
  сборщиком (`registry.py` подключает только `fabrikant_v3`). Мёртвый файл
  целиком, наравне с `b2b_center_auth.py` (v1, вытеснен `_auth_v2.py`).
  Не удалялись в этом цикле — не влияют на работоспособность.
- `tests/test_telegram_crm_wiring.py:49` — неиспользуемая локальная
  переменная `analysis` в тесте. Не влияет на поведение, не исправлялось.

## Выполненные проверки (все GREEN, поверх патченного `0c1b38c`)
- `python -m unittest discover -s tests` — 70/70
- `python test_b2b_parser.py` — 6/6 (было 3/5 failing до фикса №1)
- `python tests/test_b2b_reliable_adapter.py` — 2/2
- `python tests/test_b2b_quality_gate.py` — 4/4
- `pytest -q tests` — 202 passed, 3 subtests passed
- `pytest -q tests/test_b2b_pagination.py tests/test_keyword_filter_morphology.py` — 6/6
- `pytest -q tests/test_market_analytics.py` — 1/1
- `python tests/test_excel_export_integration.py` — PASS (17 колонок, схема ОК)
- `python -m pyflakes .` — только 3 некритичных findings, описаны выше

Каждый фикс проверен на то, что regression-тест реально падает без фикса
(включая ручной откат `to_utc()` в fabrikant_v3.py и проверку `NameError`
до добавления импорта `BASE_URL`) — не false-green.

## Точечно перепроверено (без изменений — уже корректно)
- `Orchestrator._merge_detail` / `_normalize_tender_datetimes`: даже если бы
  фикс №4 не был внесён, оркестратор всё равно перенормализует таймзоны при
  слиянии деталей в `run_cycle` — но `get_details()`, вызванный напрямую
  (вне оркестратора), возвращал бы ненормализованный объект. Фикс №4
  оправдан как defense-in-depth и для консистентности с паттерном `to_utc()`.
- `Orchestrator._deduplicate_pairs`, `_passes_criteria`, `_normalize_region`,
  `_passes_regions`: логика корректна, без изменений.
- `src/collectors/rosatom.py`: все datetime-поля проходят через конструктор
  `Tender(...)`, ни одного post-construction присвоения — бага класса №4 нет.
- `src/collectors/b2b_center_reliable.py`: пагинация и merge с
  `ModernB2BCenterCollector._parse_search_html` структурно корректны.

## Что осталось не проверено в этом цикле
- Полный аудит `eis_zakupki.py` (2252 строки) — просмотрен точечно, не построчно.
- Telegram callbacks end-to-end, CRM-борд под реальной конкурентной нагрузкой.
- Live keyword smoke (`станок`, `подшипник`, `лебедка`) против реальных площадок
  — недоступно из этой среды (см. "Среда выполнения").
- Очистка мёртвого кода (`fabrikant.py`, `b2b_center_auth.py` v1, дублирующийся
  `_extract_customer_from_soup`) — идентифицирована, не выполнена.

## Следующий шаг
1. Применить изменённые файлы из `PATCHES/` через GitHub web UI (список файлов
   ниже) поверх текущего `main` (`0c1b38c`) — **НЕ удалять** и не перезаписывать
   бинарный `claude_16.09.2026.zip`, его можно удалить отдельным коммитом после
   подтверждения, что все 4 файла из архива (b2b_center.py, тест, patch,
   checkpoint STEP-50) уже покрыты содержимым этого STEP-51.
2. Прогнать полный CI на GitHub runner для живого browser-доступа к площадкам.
3. Не мерджить `integration/crm-board-layer` — рассмотреть закрытие PR #7 как
   superseded, если он ещё открыт.
4. Рассмотреть удаление мёртвого кода, отмеченного в разделе "Статический анализ".

## Изменённые файлы (11)
- src/collectors/b2b_center.py
- src/collectors/browser_public.py
- src/collectors/browser_public_reliable.py
- src/collectors/eis_reliable.py
- src/collectors/fabrikant_v3.py
- src/collectors/tenderguru_fallback.py
- test_b2b_parser.py
- tests/test_browser_public_parser.py
- tests/test_eis_commercial_adapter.py
- tests/test_fabrikant_v3_date_contract.py
- tests/test_tenderguru_fallback.py
