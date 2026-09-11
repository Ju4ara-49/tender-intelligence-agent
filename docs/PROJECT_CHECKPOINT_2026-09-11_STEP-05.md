# Контрольная точка — 2026-09-11 — STEP-05

HEAD: `d72cde96388f73217337f3873c47345c8a855527`

## Аудит площадок
- Реестр подтверждён: EIS, B2B-Center, Фабрикант, RTS-Tender, TMK, Росатом.
- B2B reliable discovery намеренно откладывает strict keyword gate до enrichment — это соответствует pipeline.
- Rosatom detail parser уже заполняет price/deadline/start/end/customer/region/law/advance/postpayment/application security/contract security.
- Fabrikant V3 доработан: detail text теперь обогащается advance, postpayment и обеими security; значения также сохраняются в raw_data.

## Тест
Добавлен `tests/test_fabrikant_contract.py` на коммерческие поля Фабриканта.

## Следующий шаг
Аудит RTS/TMK generic browser reliable collector и его date/price/field extraction; затем отдельная контрольная точка.
