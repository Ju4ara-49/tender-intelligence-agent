from src.collectors.detail_contract import enforce_detail_contract
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


def test_detail_contract_extracts_inn() -> None:
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
