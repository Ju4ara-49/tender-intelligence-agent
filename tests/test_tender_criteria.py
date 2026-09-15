import pytest

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


def test_region_filter_matches_one_value_in_multi_region_tender():
    criteria = TenderCriteria(regions=["Москва"])
    assert Orchestrator._passes_regions(_tender(region="Москва, Московская область"), criteria.regions) is True


def test_empty_region_filter_values_do_not_reject_tender():
    assert Orchestrator._passes_regions(_tender(region="Москва"), ["", "  "]) is True



def test_criteria_rejects_contradictory_price_range():
    with pytest.raises(ValueError, match="min_price"):
        TenderCriteria(min_price=100, max_price=50)


def test_criteria_rejects_contradictory_application_security_range():
    with pytest.raises(ValueError, match="min_application_security_percent"):
        TenderCriteria(min_application_security_percent=6, max_application_security_percent=5)


def test_criteria_rejects_negative_submission_days():
    with pytest.raises(ValueError, match="min_submission_days"):
        TenderCriteria(min_submission_days=-1)


def test_criteria_normalizes_ai_score_and_lists():
    criteria = TenderCriteria(min_ai_score=150, exclude_keywords=["  test ", "TEST", ""], regions=[" Москва ", "Москва"])
    assert criteria.min_ai_score == 100
    assert criteria.exclude_keywords == ["test"]
    assert criteria.regions == ["Москва"]


def test_criteria_rejects_non_finite_numeric_values():
    with pytest.raises(ValueError, match="конечным числом"):
        TenderCriteria(min_price=float("nan"))
    with pytest.raises(ValueError, match="конечным числом"):
        TenderCriteria(max_price=float("inf"))


def test_criteria_store_update_rejects_contradictory_persisted_range(tmp_path):
    db = TenderDatabase(tmp_path / "criteria.db")
    store = CriteriaStore(db)
    store.update("u1", min_price=100, max_price=200)
    with pytest.raises(ValueError, match="min_price"):
        store.update("u1", min_price=300)
    current = store.get("u1")
    assert current.min_price == 100
    assert current.max_price == 200
