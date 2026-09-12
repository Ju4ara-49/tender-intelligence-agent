# Контрольная точка — 2026-09-12 — STEP-27

## HEAD
`d261b5d97e2f7b6c8577696afe65296bc3c5a6e5`

## Результат прогона
CI #414 завершился **FAILURE** несмотря на:
- unittest: PASS
- B2B parser: PASS
- B2B reliable adapter: PASS
- B2B quality gate: PASS
- search pipeline: PASS
- analytics: PASS
- Excel integration: PASS
- Excel artifact check: PASS

Единственный отказ был в полном pytest:
- `tests/test_browser_tender_contract.py::test_browser_detail_extracts_spaced_customer_inn`
- фактическое значение: `""`
- ожидалось: `7812345678`
- 86 passed / 1 failed.

## Исправление
Причина найдена в browser reliable detail fallback: общий `detail_contract` для этого пути не восстанавливал ИНН, а browser mixin сам не извлекал `customer_inn`.

Исправлено:
- добавлено извлечение ИНН в `ReliableBrowserSearchMixin._parse_detail`;
- поддержаны пробелы между цифрами;
- сохранено ограничение 10/12 цифр;
- удалено дублирование предупреждения `RESULT_PARSER_ZERO`.

## Следующий прогон
После исправления автоматически запущены CI и Browser Diagnostics для нового HEAD. Требуется дождаться обоих результатов и только затем фиксировать следующий checkpoint.
