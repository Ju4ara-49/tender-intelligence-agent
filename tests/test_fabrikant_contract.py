from datetime import datetime

from src.collectors.fabrikant_v2 import FabrikantV2Collector
from src.collectors.fabrikant_v3 import FabrikantV3Collector
from src.models.tender import Tender


def test_fabrikant_v3_enriches_commercial_terms(monkeypatch):
    base = Tender(
        platform="fabrikant",
        external_id="123",
        title="Поставка запасных частей",
        url="https://soap2.fabrikant.ru/223/procedure/123",
        description=(
            "Заказчик: ООО Ромашка. Регион: Санкт-Петербург. "
            "Дата публикации: 11.09.2026. Аванс 30%. "
            "Отсрочка платежа 15 дней. Обеспечение заявки 2%. "
            "Обеспечение исполнения договора 5%."
        ),
        price=1500000,
        deadline=datetime(2026, 9, 20),
        published_at=datetime(2026, 9, 11),
        start_date=datetime(2026, 9, 11),
    )

    monkeypatch.setattr(FabrikantV2Collector, "get_details", lambda self, external_id: base)
    detailed = FabrikantV3Collector({}).get_details("123")

    assert detailed is not None
    assert detailed.advance_required is True
    assert detailed.advance_percent == 30
    assert detailed.postpayment_days == 15
    assert detailed.application_security_percent == 2
    assert detailed.contract_security_percent == 5
    assert detailed.raw_data["advance_payment"]["percent"] == 30
    assert detailed.raw_data["postpayment"]["days"] == 15
    assert detailed.raw_data["application_security"]["percent"] == 2
    assert detailed.raw_data["contract_security"]["percent"] == 5
