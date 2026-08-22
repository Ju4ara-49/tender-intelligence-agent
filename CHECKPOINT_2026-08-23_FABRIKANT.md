# Tender Intelligence Agent — контрольная точка 2026-08-23

## Точка продолжения
Дата: 23.08.2026
Ветка: `main`

## GitHub / локальный запуск
- GitHub-подключение подтверждено и работает: `Ju4ara-49/tender-intelligence-agent` доступен для чтения и записи.
- Последняя подтверждённая локальная команда запуска: `python -m src.main bot`.
- Telegram-бот запускается.
- Ollama/Qwen работает: `provider=ollama`, модель `qwen3:8b`, URL `http://localhost:11434`.

## Что исправлено
### 1. Fabrikant V2 действительно начал получать структурированные поля
После переключения registry на `FabrikantV2Collector` в search/detail pipeline появились `customer=True` и `deadline=...` вместо постоянного `None`.

Это подтвердило первоначальный диагноз: старый collector терял данные строки реестра Fabrikant.

### 2. Найдена следующая проблема: detail parser перезаписывал правильные даты
В прогоне №057 были значения:
- `0744200000226005445` — deadline `2026-07-01`
- `0816500000626009862` — deadline `2026-06-17`
- `0368100002426000048` — deadline `2026-05-28`
- `0816500000626005936` — deadline `2026-04-22`
- `0346200005426000015` — deadline `2026-02-18`
- `0301300051525000248` — deadline `2025-07-17`
- `0848300058123000277` — deadline `2023-09-05`

Часть этих дат является исторической. Причина в том, что detail page может содержать несколько дат, и общий detail parser мог выбирать не ту дату и перезаписывать значение, полученное из строки реестра.

### 3. Исправлен orchestrator
Коммит `480dcbb181efeda6dd85ccc165d516a1e4b52fef`:
- если `deadline/published_at/customer/region` уже получены из Fabrikant search row, detail page больше не имеет права их перезаписывать;
- detail page используется как дополнение, а не как источник истины для базовых полей.

Коммит `1c736c89014845304473ab85c651eeed11f5b608`:
- для Fabrikant добавлен контроль `lookback_days` по `published_at` до загрузки дорогой detail page;
- старые процедуры отбрасываются до `get_details()`;
- это предотвращает обработку архивных процедур и ложных исторических deadline.

## Что показал прогон №057
`found=138 filtered=21 new=0 analyzed=0 notified=0 dup=2 excluded=19 details=21 failed=0`.

Это важный результат: V2 уже достаёт даты, но большинство найденных Fabrikant процедур оказались старыми/неподходящими по сроку подачи. Поэтому AI не запускался. Это не ошибка Ollama.

## Текущая архитектура Fabrikant
- `src/collectors/fabrikant_v2.py` — активный collector через `src/collectors/registry.py`.
- `src/collectors/fabrikant.py` — старый промежуточный вариант, пока не удалять.
- `src/collectors/browser_public.py` — Playwright/browser detail flow.
- `src/orchestrator.py` — теперь защищает базовые поля search row от перезаписи detail parser.

## Следующий обязательный тест
На локальной машине:
```powershell
cd C:\Users\Ju4ara\Projects\tender-intelligence-agent
git pull
python -m src.main bot
```

После запуска выполнить новый поиск с Fabrikant.

Проверить в логе:
1. Fabrikant не должен массово загружать старые процедуры с датами 2025/2024/2023.
2. Для свежих процедур должна быть строка вида:
   `fabrikant: детали загружены <ID> | price=... | customer=True | deadline=<актуальный deadline>`
3. В Telegram/Excel должны появляться `дата закупки`, `заказчик`/`Подробнее`, `регион` и актуальный `до`, если эти данные есть в строке реестра.
4. Особо проверить свежие 44-ФЗ результаты, а не старые ID из прошлых поисков.

## Важно
Не менять без необходимости:
- Telegram-интерфейс и настройки;
- нумерацию поисков;
- Excel-связку;
- EIS/B2B рабочую логику;
- Ollama/Qwen.

## Если после нового теста Fabrikant снова отдаёт старые даты
Следующий шаг — не расширять generic date parser. Нужно сохранить в `raw_data.search_row` фактические `headers + values` строки реестра и по конкретному проблемному ID проверить, какие именно значения возвращает таблица. Если таблица сама отдаёт корректный deadline, исправлять только mapping колонок.

## Контрольные коммиты
- `3c145aa` — переход к Fabrikant V2 и checkpoint.
- `480dcbb181efeda6dd85ccc165d516a1e4b52fef` — защита search-row дат/полей от detail overwrite.
- `1c736c89014845304473ab85c651eeed11f5b608` — Fabrikant lookback до detail loading.
