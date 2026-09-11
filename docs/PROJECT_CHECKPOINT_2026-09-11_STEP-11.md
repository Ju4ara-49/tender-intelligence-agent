# Контрольная точка — 2026-09-11 — STEP-11

HEAD: `33e6321e0a6b821f280c1da539fde149626b1618`

## Исправлены ошибки CI
Предыдущий full pytest run показал 3 ошибки:
1. RTS/TMK browser detail не извлекал `Регион поставки` из конкретной HTML-комбинации — добавлен fallback в reliable browser mixin.
2. Database hardening test использовал `datetime.now()` дважды, поэтому одинаковый тендер фактически имел разные deadline — тест сделан детерминированным.
3. Новая семантика unknown commercial fields сохранила строгий reject, но возвращает прежние стабильные reason codes (`max_postpayment_days`, `max_application_security_percent`, `max_contract_security_percent`) для совместимости.

## Следующий шаг
Проверить новый CI run. Только после зелёного full pytest переходить дальше.
