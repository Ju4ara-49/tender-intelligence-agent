import pytest

from datetime import datetime, timedelta, timezone

from src.models.tender import Tender
from src.orchestrator import Orchestrator
from src.telegram_settings import CriteriaStore, TenderCriteria
from src.storage.database import TenderDatabase


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


def test_criteria_store_set_user_id_is_explicit_context(tmp_path):
    db = TenderDatabase(tmp_path / "criteria-context.db")
    store = CriteriaStore(db)
    store.set_user_id("user-42")
    store.update(min_price=123)
    assert store.get().min_price == 123
    assert store.get("user-42").min_price == 123
    assert store.get("default").min_price != 123


def test_criteria_store_set_user_id_normalizes_blank_to_default(tmp_path):
    db = TenderDatabase(tmp_path / "criteria-default.db")
    store = CriteriaStore(db)
    store.set_user_id("  ")
    store.update(min_price=456)
    assert store.get("default").min_price == 456


def test_criteria_store_context_isolated_by_async_context(tmp_path):
    import asyncio
    import contextvars

    db = TenderDatabase(tmp_path / "criteria-contextvars.db")
    store = CriteriaStore(db)
    store.update("user-a", min_price=100)
    store.update("user-b", min_price=200)

    async def read_current(user_id):
        store.set_user_id(user_id)
        await asyncio.sleep(0)
        return store.get().min_price

    async def scenario():
        first = asyncio.create_task(read_current("user-a"))
        second = asyncio.create_task(read_current("user-b"))
        return await asyncio.gather(first, second)

    assert asyncio.run(scenario()) == [100, 200]


def test_customer_filter_matches_by_name():
    criteria = TenderCriteria(customer="ООО Ромашка")
    ok, reason = Orchestrator._passes_criteria(_tender(customer="Заказчик ООО Ромашка"), criteria)
    assert ok is True
    ok, reason = Orchestrator._passes_criteria(_tender(customer="ООО Солнечко"), criteria)
    assert ok is False
    assert reason == "customer"


def test_customer_filter_empty_string_is_normalized_to_none():
    criteria = TenderCriteria(customer="  ")
    assert criteria.customer is None


def test_customer_inn_filter_matches_exact():
    criteria = TenderCriteria(customer_inn="7701234567")
    ok, reason = Orchestrator._passes_criteria(_tender(customer_inn="7701234567"), criteria)
    assert ok is True
    ok, reason = Orchestrator._passes_criteria(_tender(customer_inn="7709999999"), criteria)
    assert ok is False
    assert reason == "customer_inn"


def test_customer_inn_filter_normalizes_spaces():
    criteria = TenderCriteria(customer_inn="770 123 4567")
    ok, _ = Orchestrator._passes_criteria(_tender(customer_inn="7701234567"), criteria)
    assert ok is True


def test_customer_inn_filter_rejects_missing_inn():
    criteria = TenderCriteria(customer_inn="7701234567")
    ok, reason = Orchestrator._passes_criteria(_tender(customer_inn=""), criteria)
    assert ok is False
    assert reason == "customer_inn"


def test_law_type_filter_matches_by_shorthand():
    criteria = TenderCriteria(law_type="44")
    ok, reason = Orchestrator._passes_criteria(_tender(law_type="44-ФЗ"), criteria)
    assert ok is True
    ok, reason = Orchestrator._passes_criteria(_tender(law_type="223-ФЗ"), criteria)
    assert ok is False
    assert reason == "law_type"


def test_law_type_filter_matches_full_name():
    criteria = TenderCriteria(law_type="44-ФЗ")
    ok, reason = Orchestrator._passes_criteria(_tender(law_type="44-ФЗ"), criteria)
    assert ok is True
    ok, reason = Orchestrator._passes_criteria(_tender(law_type=""), criteria)
    assert ok is False
    assert reason == "law_type"


def test_law_type_filter_empty_string_is_normalized_to_none():
    criteria = TenderCriteria(law_type="  ")
    assert criteria.law_type is None
