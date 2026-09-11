from datetime import datetime, timedelta, timezone

from src.collectors.eis_reliable import ReliableEisZakupkiCollector
from src.models.tender import Tender


def test_eis_adapter_populates_unified_commercial_fields(monkeypatch):
    collector = ReliableEisZakupkiCollector()
    detailed = Tender(
        platform="eis",
        external_id="1234567890123",
        title="Поставка",
        url="https://example.test/123",
        description=(
            "Аванс 30%. Отсрочка платежа 45 календарных дней. "
            "Обеспечение заявки 2%. Обеспечение исполнения контракта 10%."
        ),
        deadline=datetime.now(timezone.utc) + timedelta(days=20),
    )
    monkeypatch.setattr(collector.__class__.__bases__[0], "get_details", lambda self, external_id: detailed)

    result = collector.get_details(detailed.external_id)

    assert result is not None
    assert result.advance_required is True
    assert result.advance_percent == 30
    assert result.postpayment_days == 45
    assert result.application_security_percent == 2
    assert result.contract_security_percent == 10
    assert result.raw_data["commercial_conditions"]["postpayment_days"] == 45
