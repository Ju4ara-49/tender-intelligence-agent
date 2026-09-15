# STEP-49 — 15.09.2026

## Контрольная точка
Проект продолжает работу от:
`eb76f691a7969f0d2a0ebcc1d602e8edeaf85eba`

## Состояние
- Keyword smoke: `станок`, `подшипник`, `лебедка`.
- Browser collector восстановлен после обнаруженного SyntaxError.
- Browser collector теперь fail-closed при timeout/search-control/access challenge.
- RTS использует публичную 223-ФЗ поверхность с bounded public-index fallback.
- TMK использует актуальный публичный auction registry.
- Keyword relevance проверяется после browser parsing, включая русские словоформы.
- CI #746 — SUCCESS: unittest, B2B parser/reliable/quality, full pytest, search pipeline, analytics, Excel integration/artifact checks — GREEN.

## Обнаруженный дефект этого цикла
Переписывание `src/collectors/browser_public.py` ввело незакрытую скобку в `_tender_matches_query`. CI #745 выявил это до публикации результата. Исправлено в `eb76f691...`.

## Внешняя доступность
Linux и Windows Browser Diagnostics для HEAD `eb76f691...` ещё выполнялись на момент записи контрольной точки. EIS/RTS могут иметь hosted-runner network timeout/reset; это не превращается в ложный `0 results`. Где безопасно, используется bounded public fallback с явной provenance.

## Следующий обязательный шаг
Дождаться Linux/Windows browser diagnostics и live keyword smoke для `станок`, `подшипник`, `лебедка`. Любой внутренний failure, parser mismatch, false-positive или false-green → root cause → исправление → regression test → полный CI → live/browser повтор.

## Алгоритм
HEAD/checkpoint → collectors → detail contract/normalization → filters → dedup/storage/notification fingerprints → AI/Ollama → Telegram/notifications/CRM → Excel → scheduler/orchestrator/CLI → CI → Linux browser → Windows browser → artifact/live diagnostics. Не объявлять 100% до GREEN всех доступных code-level gates и завершения внешних проверок.
