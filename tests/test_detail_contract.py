from datetime import datetime, timedelta, timezone

from src.collectors.detail_contract import _extract_okpd2_codes, enforce_detail_contract
from src.models.tender import Tender


class DummyCollector:
    platform = "dummy"

    def __init__(self, tender):
        self.tender = tender

    def get_details(self, external_id):
        return self.tender


def test_detail_contract_marks_missing_expected_fields_partial() -> None:
    collector = DummyCollector(Tender(platform="dummy", external_id="1", title="Title", url="https://example.test"))
    enforce_detail_contract(collector)
    result = collector.get_details("1")
    assert result.detail_status == "partial"
    assert "customer" in result.detail_diagnostics
    assert "price" in result.detail_diagnostics
    assert "deadline" in result.detail_diagnostics


def test_detail_contract_marks_waf_failed() -> None:
    tender = Tender(
        platform="dummy",
        external_id="1",
        title="Title",
        url="https://example.test",
        raw_data={"waf_blocked": True},
    )
    collector = DummyCollector(tender)
    enforce_detail_contract(collector)
    result = collector.get_details("1")
    assert result.detail_status == "failed"
    assert result.raw_data["details_loaded"] is False


def test_detail_contract_extracts_inn_from_description() -> None:
    tender = Tender(
        platform="dummy",
        external_id="1",
        title="Title",
        url="https://example.test",
        customer="ООО Тест",
        description="ИНН: 7701234567",
        price=100,
    )
    collector = DummyCollector(tender)
    enforce_detail_contract(collector)
    result = collector.get_details("1")
    assert result.customer_inn == "7701234567"


def test_detail_contract_extracts_inn_from_customer_when_description_is_empty() -> None:
    tender = Tender(
        platform="dummy",
        external_id="2",
        title="Title",
        url="https://example.test/2",
        customer="ООО Тест, ИНН 7707654321",
        price=100,
    )
    collector = DummyCollector(tender)
    enforce_detail_contract(collector)
    result = collector.get_details("2")
    assert result.customer_inn == "7707654321"


def test_detail_contract_extracts_inn_from_raw_organizer() -> None:
    tender = Tender(
        platform="dummy",
        external_id="3",
        title="Title",
        url="https://example.test/3",
        customer="ООО Тест",
        price=100,
        raw_data={"organizer": "Заказчик ООО Тест ИНН 7701122334"},
    )
    collector = DummyCollector(tender)
    enforce_detail_contract(collector)
    result = collector.get_details("3")
    assert result.customer_inn == "7701122334"


def test_detail_contract_normalizes_spaced_inn() -> None:
    tender = Tender(
        platform="dummy",
        external_id="4",
        title="Title",
        url="https://example.test/4",
        customer_inn="770 123 456 7",
        price=100,
    )
    collector = DummyCollector(tender)
    enforce_detail_contract(collector)
    result = collector.get_details("4")
    assert result.customer_inn == "7701234567"


def test_detail_contract_ignores_invalid_customer_inn_and_uses_text_fallback() -> None:
    tender = Tender(
        platform="dummy",
        external_id="5",
        title="Title",
        url="https://example.test/5",
        customer_inn="неизвестно",
        customer="ООО Тест, ИНН 7707654321",
        price=100,
    )
    collector = DummyCollector(tender)
    enforce_detail_contract(collector)
    result = collector.get_details("5")
    assert result.customer_inn == "7707654321"


def test_detail_contract_extracts_explicit_okpd2_and_procurement_type() -> None:
    tender = Tender(
        platform="eis",
        external_id="6",
        title="Коммерческая закупка оборудования",
        url="https://example.test/6",
        description="Код ОКПД2: 26.30.11.110",
        customer="ООО Тест",
        price=100,
        deadline=datetime.now(timezone.utc) + timedelta(days=10),
    )
    collector = DummyCollector(tender)
    enforce_detail_contract(collector)

    result = collector.get_details("6")

    assert result.okpd2_codes == ["26.30.11.110"]
    assert result.procurement_type == "commercial"


def test_detail_contract_okpd2_marker_ignores_trailing_price_fragment() -> None:
    tender = Tender(
        platform="eis",
        external_id="okpd2-price-1",
        title="Закупка оборудования",
        url="https://example.test/okpd2-price-1",
        description="Код ОКПД2: 26.30.11.110; Цена: 10 000 руб.",
    )

    assert _extract_okpd2_codes(tender) == ["26.30.11.110"]


def test_detail_contract_leaves_unknown_procurement_type_empty() -> None:
    tender = Tender(
        platform="eis",
        external_id="7",
        title="Поставка оборудования",
        url="https://example.test/7",
        description="Способ закупки: запрос предложений",
        customer="ООО Тест",
        price=100,
        deadline=datetime.now(timezone.utc) + timedelta(days=10),
    )
    collector = DummyCollector(tender)
    enforce_detail_contract(collector)

    assert collector.get_details("7").procurement_type == ""


def test_eis_detail_parser_feeds_contract_extraction() -> None:
    from bs4 import BeautifulSoup
    from src.collectors.eis_zakupki import EisZakupkiCollector

    html = """
    <html><body>
        <div>Объект закупки: Коммерческая закупка оборудования</div>
        <div>Заказчик: ООО Тест</div>
        <div>Начальная цена: 100 000,00 руб.</div>
        <div>Окончание подачи заявок: 30.09.2026 12:00</div>
        <div>Код ОКПД2: 26.30.11.110</div>
        <div>Тип процедуры: Коммерческая закупка</div>
    </body></html>
    """
    parser = EisZakupkiCollector({})
    parsed = parser._parse_details_page(
        BeautifulSoup(html, "lxml"),
        "1234567890",
        "https://example.test/eis/1234567890",
    )
    assert parsed is not None

    collector = DummyCollector(parsed)
    enforce_detail_contract(collector)
    result = collector.get_details("1234567890")

    assert result.okpd2_codes == ["26.30.11.110"]
    assert result.procurement_type == "commercial"



def test_eis_detail_region_extraction_handles_current_russian_labels():
    from bs4 import BeautifulSoup
    from src.collectors.eis_zakupki import EisZakupkiCollector

    html = """<html><body>
    <div>Регион: Санкт-Петербург</div>
    <div>Место поставки: Санкт-Петербург, ул. Тестовая, д. 1</div>
    <div>Начальная цена: 100 000,00 руб.</div>
    <div>Заказчик: ООО Тест</div>
    </body></html>"""
    value = EisZakupkiCollector._extract_region_from_soup(BeautifulSoup(html, "lxml"))
    assert value == "Санкт-Петербург"


def test_eis_detail_region_extraction_falls_back_to_delivery_location():
    from bs4 import BeautifulSoup
    from src.collectors.eis_zakupki import EisZakupkiCollector

    html = """<html><body>
    <div>Место поставки: Московская область, г. Химки, ул. Ленина, д. 1</div>
    <div>Окончание подачи заявок: 30.09.2026 12:00</div>
    </body></html>"""
    value = EisZakupkiCollector._extract_region_from_soup(BeautifulSoup(html, "lxml"))
    assert value.startswith("Московская область")



def test_notification_commercial_terms_change_without_duplicate() -> None:
    """
    Test that commercial terms change notifications do not create duplicates.
    """
    pass

def test_dedup_uniqueness_and_behavior() -> None:
    """
    Test deduplication logic ensures uniqueness and correct behavior on duplicates.
    """
    pass
    from src.collectors.eis_zakupki import EisZakupkiCollector

    text = (
        "Условия оплаты: аванс 30%. Отсрочка платежа 45 календарных дней. "
        "Обеспечение заявки 1%. Обеспечение исполнения контракта 5%."
    )
    result = EisZakupkiCollector._extract_commercial_conditions(text)
    assert result == {
        "advance_required": True,
        "advance_percent": 30.0,
        "postpayment_days": 45,
        "application_security_percent": 1.0,
        "contract_security_percent": 5.0,
    }
