from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.models.tender import Tender
from src.orchestrator import Orchestrator
from src.telegram_settings import TenderCriteria


class _DetailCollector:
    platform = "rts_tender"

    def get_details(self, external_id: str) -> Tender:
        return Tender(
            platform=self.platform,
            external_id=external_id,
            title="Поставка запасных частей — детали",
            url="https://example.test/tender/1",
            description="Расширенное описание",
            price=1_500_000,
            start_date=datetime(2026, 9, 12, 9, 0),
            end_date=datetime(2026, 9, 20, 18, 0),
            published_at=datetime(2026, 9, 11, 8, 0),
            deadline=datetime(2026, 9, 20, 18, 0),
            region="Санкт-Петербург",
            customer="ООО Ромашка",
            law_type="223-ФЗ",
            advance_required=True,
            advance_percent=30,
            postpayment_days=15,
            application_security_percent=2,
            contract_security_percent=5,
            raw_data={"items": ["подшипник"]},
        )


def _tender(**overrides) -> Tender:
    values = {
        "platform": "rts_tender",
        "external_id": "1",
        "title": "Тестовый тендер",
        "url": "https://example.test/tender/1",
        "price": 1_000_000,
        "deadline": datetime.now(timezone.utc) + timedelta(days=10),
        "advance_required": True,
        "advance_percent": 30,
        "postpayment_days": 15,
        "application_security_percent": 2,
        "contract_security_percent": 5,
    }
    values.update(overrides)
    return Tender(**values)


def test_enrichment_copies_all_common_detail_fields() -> None:
    base = _tender(start_date=None, end_date=None, deadline=None, published_at=None, advance_required=False, advance_percent=None, postpayment_days=None, application_security_percent=None, contract_security_percent=None)
    enriched, loaded = Orchestrator.__new__(Orchestrator)._enrich_tender(_DetailCollector(), base)

    assert loaded is True
    assert enriched.start_date is not None
    assert enriched.end_date is not None
    assert enriched.deadline == enriched.end_date
    assert enriched.advance_required is True
    assert enriched.advance_percent == 30
    assert enriched.postpayment_days == 15
    assert enriched.application_security_percent == 2
    assert enriched.contract_security_percent == 5
    assert enriched.customer == "ООО Ромашка"
    assert enriched.region == "Санкт-Петербург"


def test_detail_values_replace_stale_search_values() -> None:
    base = _tender(
        start_date=datetime(2026, 9, 10, 9, 0),
        end_date=datetime(2026, 9, 18, 18, 0),
        deadline=datetime(2026, 9, 18, 18, 0),
        region="Москва",
        customer="Старый заказчик",
    )
    enriched, _ = Orchestrator.__new__(Orchestrator)._enrich_tender(_DetailCollector(), base)

    assert enriched.end_date == datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)
    assert enriched.deadline == enriched.end_date
    assert enriched.region == "Санкт-Петербург"
    assert enriched.customer == "ООО Ромашка"


def test_max_postpayment_rejects_missing_value() -> None:
    tender = _tender(postpayment_days=None)
    criteria = TenderCriteria(max_postpayment_days=30)
    assert Orchestrator._passes_criteria(tender, criteria) == (False, "max_postpayment_days")


def test_max_security_rejects_missing_value() -> None:
    tender = _tender(application_security_percent=None, contract_security_percent=None)
    criteria = TenderCriteria(max_application_security_percent=5, max_contract_security_percent=10)
    assert Orchestrator._passes_criteria(tender, criteria) == (False, "max_application_security_percent")


def test_max_postpayment_and_security_accept_values_inside_limits() -> None:
    tender = _tender(postpayment_days=30, application_security_percent=5, contract_security_percent=10)
    criteria = TenderCriteria(max_postpayment_days=30, max_application_security_percent=5, max_contract_security_percent=10)
    assert Orchestrator._passes_criteria(tender, criteria) == (True, "")


def test_platform_worker_count_honors_concurrency_alias_and_bounds():
    assert Orchestrator._platform_worker_count({"concurrency": 2}, 6) == 2
    assert Orchestrator._platform_worker_count({"platform_workers": 4, "concurrency": 2}, 6) == 4
    assert Orchestrator._platform_worker_count({"concurrency": 99}, 6) == 6
    assert Orchestrator._platform_worker_count({"concurrency": 0}, 6) == 1
    assert Orchestrator._platform_worker_count({"concurrency": "bad"}, 6) == 6


def test_excel_export_uses_post_filter_result_ids_not_diagnostic_persistence_ids():
    source = Path(Orchestrator.__module__.replace(".", "/") + ".py").read_text(encoding="utf-8")
    assert "export_tender_ids: list[int] = []" in source
    assert "export_tender_ids.append(tender_id)" in source
    assert "tender_ids=export_tender_ids" in source
    assert "tender_ids=current_run_tender_ids" not in source
