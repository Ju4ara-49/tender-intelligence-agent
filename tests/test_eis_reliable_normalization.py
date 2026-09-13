from unittest.mock import patch

from src.collectors.eis_reliable import ReliableEisZakupkiCollector
from src.collectors.eis_zakupki import EisZakupkiCollector
from src.models.tender import Tender


def test_eis_reliable_persists_mutated_commercial_terms_in_normalized_state():
    base_tender = Tender(
        platform="eis",
        external_id="1234567890",
        title="Поставка подшипников",
        url="https://zakupki.gov.ru/example",
        description="Условия закупки",
        price=100000.0,
    )
    # Simulate the base collector returning a Tender whose normalized snapshot
    # was already created before the reliable enrichment mutates the fields.
    assert base_tender.raw_data["_normalized"]["advance_percent"] is None

    collector = ReliableEisZakupkiCollector()
    collector._extract_commercial_conditions = lambda text: {
        "advance_percent": 30.0,
        "advance_required": True,
        "postpayment_days": 15,
        "application_security_percent": 2.0,
        "contract_security_percent": 5.0,
    }

    with patch.object(EisZakupkiCollector, "get_details", return_value=base_tender):
        enriched = collector.get_details(base_tender.external_id)

    assert enriched is base_tender
    normalized = enriched.raw_data["_normalized"]
    assert normalized == {
        "advance_required": True,
        "advance_percent": 30.0,
        "postpayment_days": 15,
        "application_security_percent": 2.0,
        "contract_security_percent": 5.0,
        "customer_inn": "",
    }
