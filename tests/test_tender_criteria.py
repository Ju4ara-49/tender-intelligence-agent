from datetime import datetime, timedelta, timezone

from src.models.tender import Tender
from src.orchestrator import Orchestrator
from src.telegram_settings import TenderCriteria


def _tender(**kwargs) -> Tender:
    defaults = {
        "platform": "test",
        "external_id": "1",
        "title": "Поставка подшипников",
        "url": "https://example.test/1",
        "price": 1_000_000,
        "deadline": datetime.now(timezone.utc) + timedelta(days=10),
        "advance_required": True,
        "advance_percent": 30,
        "postpayment_days": 30,
        "application_security_percent": 2,
        "contract_security_percent": 5,
    }
    defaults.update(kwargs)
    return Tender(**defaults)


def test_all_business_criteria_pass():
    criteria = TenderCriteria(
        min_price=500_000,
        max_price=2_000_000,
        advance_required=True,
        min_advance_percent=20,
        max_postpayment_days=45,
        min_application_security_percent=1,
        max_application_security_percent=3,
        min_contract_security_percent=4,
        max_contract_security_percent=6,
        min_submission_days=7,
    )
    assert Orchestrator._passes_criteria(_tender(), criteria) == (True, "")


def test_missing_required_commercial_data_is_rejected():
    criteria = TenderCriteria(max_postpayment_days=45, min_application_security_percent=1)
    ok, reason = Orchestrator._passes_criteria(
        _tender(postpayment_days=None, application_security_percent=None), criteria
    )
    assert not ok
    assert reason == "max_postpayment_days"


def test_advance_and_security_limits_are_enforced():
    criteria = TenderCriteria(
        advance_required=True,
        min_advance_percent=50,
        max_application_security_percent=5,
        min_contract_security_percent=10,
        min_submission_days=7,
    )
    ok, reason = Orchestrator._passes_criteria(_tender(), criteria)
    assert not ok
    assert reason == "min_advance_percent"


def test_deadline_must_leave_full_minimum_days():
    criteria = TenderCriteria(min_submission_days=7)
    ok, reason = Orchestrator._passes_criteria(
        _tender(deadline=datetime.now(timezone.utc) + timedelta(days=6, hours=23, minutes=59)),
        criteria,
    )
    assert not ok
    assert reason == "min_submission_days"

def test_region_filter_does_not_confuse_moscow_with_moscow_oblast():
    criteria = TenderCriteria(regions=["Москва"])
    assert Orchestrator._passes_regions(_tender(region="Москва"), criteria.regions) is True
    assert Orchestrator._passes_regions(_tender(region="Московская область"), criteria.regions) is False


def test_region_filter_normalizes_common_city_and_abbreviation_forms():
    criteria = TenderCriteria(regions=["Санкт-Петербург", "Ленинградская область"])
    assert Orchestrator._passes_regions(_tender(region="г. Санкт-Петербург"), criteria.regions) is True
    assert Orchestrator._passes_regions(_tender(region="Ленинградская обл."), criteria.regions) is True


def test_empty_region_filter_values_do_not_reject_tender():
    assert Orchestrator._passes_regions(_tender(region="Москва"), ["", "  "]) is True

