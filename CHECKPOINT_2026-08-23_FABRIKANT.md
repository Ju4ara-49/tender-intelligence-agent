# Tender Intelligence Agent — контрольная точка 2026-08-23

## Точка продолжения
Дата: 23.08.2026
Ветка: `main`

## GitHub / локальный запуск
- GitHub-подключение подтверждено и работает: `Ju4ara-49/tender-intelligence-agent` доступен для чтения и записи.
- Последняя подтверждённая локальная команда запуска: `python -m src.main bot`.
- Telegram-бот запускается.
- Ollama/Qwen работает: `provider=ollama`, модель `qwen3:8b`, URL `http://localhost:11434`.

## Fabrikant — текущее состояние
Активен Fabrikant V3 через registry.

V2 уже исправил основную проблему «Фабрикант даёт почти только цену»: строка реестра и detail теперь дают customer и deadline, а orchestrator не позволяет detail parser перезаписывать корректные search-row даты/customer/region.

Оставшаяся проблема после прогонов: `region` всё ещё часто пустой, хотя Fabrikant может отдавать его отдельной колонкой реестра. Для исправления добавлен `FabrikantV3Collector`, который:
- сохраняет всю логику V2 без переписывания рабочего парсера;
- дополнительно ищет `Регион`, `Регион заказчика`, `Регион поставки`, `Место поставки`, `Место нахождения`, `Адрес поставки` непосредственно в `raw_data.search_row.headers/values`;
- сохраняет найденный регион в `Tender.region`;
- сохраняет индекс региона в `raw_data.search_row.mapping["region"]`;
- имеет консервативный fallback по очевидным названиям российских регионов в detail-тексте.

## Последний подтверждённый прогон №057
`found=138 filtered=21 new=0 analyzed=0 notified=0 dup=2 excluded=19 details=21 failed=0`.
В логах были `customer=True` и даты deadline, но часть процедур была исторической. Старые процедуры теперь отбрасываются до загрузки detail.

## Контрольные коммиты
- `3c145aa` — переход к Fabrikant V2 и checkpoint.
- `480dcbb181efeda6dd85ccc165d516a1e4b52fef` — защита search-row полей от detail overwrite.
- `1c736c89014845304473ab85c651eeed11f5b608` — lookback до detail loading.
- `ed2bed6a23f572e7db53b591e0d6bececc0f5d08` — усиление mapping полей и lookback в Fabrikant V2.
- `818d3f93fd6f24397928b9616cf6e611bbfcce7f` — добавлен Fabrikant V3 с region enrichment.
- `27a0e2bf8c25eabfaef1f9f3d9a8cea1e9161100` — registry переключён на Fabrikant V3.

## Следующий обязательный тест
```powershell
cd C:\Users\Ju4ara\Projects\tender-intelligence-agent
git pull
python -m src.main bot
```

После запуска выполнить новый поиск с включённым Fabrikant.

Проверить в логах и Telegram/Excel:
1. Старые процедуры не должны массово доходить до detail.
2. Для свежих процедур должны быть `customer=True` и актуальный `deadline`.
3. Должны появиться `published_at`/дата закупки и `region`, когда эти поля присутствуют в строке реестра.
4. В `raw_data.search_row.mapping` должен появиться ключ `region` с индексом фактической колонки.
5. Не менять Telegram, Excel, EIS/B2B и Ollama без отдельной необходимости.

## Важное наблюдение по реальному тендеру
Для закупки `0301300051525000248` внешняя карточка подтверждает, что корректные поля существуют: опубликовано 09.07.2025, окончание подачи 17.07.2025 06:00 МСК, регион Башкортостан/Уфа, заказчик ГБУЗ РБ ГКБ №21. Задача — правильно забрать эти поля из Fabrikant, а не придумывать их через AI.
