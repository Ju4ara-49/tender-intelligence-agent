from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

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


def test_search_rss_resolves_relative_link_without_nameerror():
    collector = ReliableEisZakupkiCollector({})
    rss_xml = (
        "<?xml version='1.0'?><rss><channel><item>"
        "<title>Поставка станка 44-ФЗ №0123456789012345</title>"
        "<link>/epz/order/notice/rgk/view/common-info.html?regNumber=0123456789012345</link>"
        "<guid>0123456789012345</guid>"
        "<description>Тестовое описание</description>"
        "<pubDate>Wed, 16 Sep 2026 10:00:00 +0300</pubDate>"
        "</item></channel></rss>"
    )
    with patch.object(collector, "_get", return_value=Mock(text=rss_xml)):
        results = collector._search_rss("станок", None)
    assert len(results) == 1
    assert results[0].url == (
        "https://zakupki.gov.ru/epz/order/notice/rgk/view/common-info.html"
        "?regNumber=0123456789012345"
    )
