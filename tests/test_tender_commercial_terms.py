from src.models.tender import Tender


def test_tender_recovers_commercial_terms_from_detail_text():
    tender = Tender(
        platform="eis",
        external_id="1",
        title="Поставка",
        url="https://example.test/1",
        description=(
            "Условия оплаты: аванс 30%. Отсрочка платежа 45 календарных дней. "
            "Обеспечение заявки 2%. Обеспечение исполнения контракта 10%."
        ),
    )
    assert tender.advance_required is True
    assert tender.advance_percent == 30
    assert tender.postpayment_days == 45
    assert tender.application_security_percent == 2
    assert tender.contract_security_percent == 10


def test_existing_explicit_values_are_not_overwritten():
    tender = Tender(
        platform="eis",
        external_id="2",
        title="Поставка",
        url="https://example.test/2",
        description="Аванс 30%. Обеспечение заявки 2%.",
        advance_percent=20,
        postpayment_days=10,
        application_security_percent=1,
    )
    assert tender.advance_percent == 20
    assert tender.advance_required is True
    assert tender.postpayment_days == 10
    assert tender.application_security_percent == 1
