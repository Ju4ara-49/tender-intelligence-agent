from src.collectors.browser_public_reliable import ReliableRtsTenderCollector


def test_browser_detail_populates_common_tender_contract_fields():
    html = """
    <html><body>
      <h1>Поставка запасных частей</h1>
      Заказчик: ООО Ромашка
      Регион поставки: Санкт-Петербург
      Закон: 223-ФЗ
      НМЦ: 1 250 000,00 руб.
      Дата публикации: 10.09.2026 12:30
      Дата начала: 11.09.2026 09:00
      Дата окончания: 20.09.2026 18:00
      Аванс: 30%
      Срок оплаты: 15 дней
      Обеспечение заявки: 2%
      Обеспечение контракта: 5%
    </body></html>
    """

    tender = ReliableRtsTenderCollector()._parse_detail(
        html,
        "1234567",
        "https://www.rts-tender.ru/procedure/1234567",
    )

    assert tender.title == "Поставка запасных частей"
    assert tender.price == 1_250_000.0
    assert tender.customer == "ООО Ромашка"
    assert tender.region == "Санкт-Петербург"
    assert tender.law_type == "223-ФЗ"
    assert tender.published_at is not None
    assert tender.start_date is not None
    assert tender.deadline is not None
    assert tender.end_date is not None
    assert tender.advance_required is True
    assert tender.advance_percent == 30.0
    assert tender.postpayment_days == 15
    assert tender.application_security_percent == 2.0
    assert tender.contract_security_percent == 5.0
