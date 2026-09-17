from __future__ import annotations

from unittest.mock import patch

from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector
from src.collectors.eis_reliable import ReliableEisZakupkiCollector
from src.collectors.fabrikant_v3 import FabrikantV3Collector
import src.collectors.registry as registry


def test_eis_procedure_dates_keep_explicit_time() -> None:
    start, end = ReliableEisZakupkiCollector._extract_procedure_dates(
        "Дата начала подачи заявок: 15.09.2026 12:56 Дата окончания подачи заявок: 22.09.2026 08:00"
    )
    assert start is not None
    assert end is not None
    assert (start.hour, start.minute) == (12, 56)
    assert (end.hour, end.minute) == (8, 0)


def test_eis_customer_rejects_navigation_noise_and_keeps_organization() -> None:
    soup = BeautifulSoup(
        """
        <div>Сведения о закупке Реестровый номер извещения Протоколы</div>
        <table><tr><td class='tableBlock__col_header'>АО "Реальный заказчик"</td></tr></table>
        """,
        "html.parser",
    )
    assert ReliableEisZakupkiCollector._extract_customer_from_soup(soup) == 'АО "Реальный заказчик"'


def test_eis_223_stub_is_rejected() -> None:
    collector = ReliableEisZakupkiCollector({"timeout_seconds": 1})
    soup = BeautifulSoup(
        "<html><body>Сведения о закупке Реестровый номер извещения Протоколы Личный кабинет</body></html>",
        "html.parser",
    )
    assert collector._parse_details_page(
        soup,
        "12345678901234567890",
        "https://zakupki.gov.ru/223/purchase/public/purchase/info/common-info.html?regNumber=12345678901234567890",
    ) is None


def test_fabrikant_223_header_and_region_matching() -> None:
    html = """
    <table>
      <tr>
        <th>Наименование закупки (номер извещения)</th>
        <th>Заказчик</th>
        <th>Регион заказчика</th>
      </tr>
      <tr>
        <td><a href='/223/procedure/123456'>Подшипники</a></td>
        <td>АО Заказчик</td>
        <td>Свердловская область</td>
      </tr>
    </table>
    """
    collector = FabrikantV3Collector({"max_results": 20})
    results = collector._parse_results(html)
    assert len(results) == 1
    assert results[0].title == "Подшипники"
    assert results[0].region == "Свердловская область"


def test_registry_constructs_each_enabled_collector_once() -> None:
    class Probe(BaseCollector):
        platform = "probe"
        calls = 0

        def __init__(self, config=None):
            type(self).calls += 1
            self.config = config or {}

        def search(self, keywords, since=None):
            return []

        def get_details(self, external_id):
            return None

    config = {"collectors": {"probe": {"enabled": True, "max_results": 7}}}
    with patch.object(registry, "ALL_COLLECTORS", [Probe]), patch.object(
        registry, "enforce_detail_contract", lambda collector: None
    ):
        collectors = registry.get_enabled_collectors(config)

    assert len(collectors) == 1
    assert Probe.calls == 1
    assert collectors[0].config["max_results"] == 7
