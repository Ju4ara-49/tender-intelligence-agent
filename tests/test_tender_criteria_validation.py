import pytest

from src.telegram_settings import CriteriaStore, TenderCriteria
from src.storage.database import TenderDatabase


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_price": -1},
        {"max_price": -1},
        {"min_price": 200, "max_price": 100},
        {"min_advance_percent": -1},
        {"min_advance_percent": 101},
        {"min_application_security_percent": 6, "max_application_security_percent": 5},
        {"min_contract_security_percent": 6, "max_contract_security_percent": 5},
        {"max_postpayment_days": -1},
        {"min_submission_days": -1},
        {"min_ai_score": -1},
        {"min_ai_score": 101},
        {"min_ai_score": True},
    ],
)
def test_invalid_criteria_are_rejected(kwargs):
    with pytest.raises(ValueError):
        TenderCriteria(**kwargs)


def test_non_finite_price_is_rejected():
    with pytest.raises(ValueError):
        TenderCriteria(min_price=float("nan"))
    with pytest.raises(ValueError):
        TenderCriteria(max_price=float("inf"))


def test_criteria_normalizes_lists_and_accepts_valid_boundary_values():
    criteria = TenderCriteria(
        min_price=0,
        max_price=100,
        min_advance_percent=100,
        min_application_security_percent=0,
        max_application_security_percent=100,
        min_contract_security_percent=0,
        max_contract_security_percent=100,
        max_postpayment_days=0,
        min_submission_days=0,
        min_ai_score=100,
        exclude_keywords=["  А", "а", ""],
        regions=[" СПб ", "спб"],
    )

    assert criteria.min_price == 0
    assert criteria.min_advance_percent == 100
    assert criteria.exclude_keywords == ["А"]
    assert criteria.regions == ["СПб"]


def test_store_update_validates_against_existing_values_and_does_not_partially_write(tmp_path):
    db = TenderDatabase(tmp_path / "criteria.db")
    store = CriteriaStore(db)
    store.update("u1", min_price=100, max_price=1000)

    with pytest.raises(ValueError):
        store.update("u1", min_price=2000)

    current = store.get("u1")
    assert current.min_price == 100
    assert current.max_price == 1000


def test_store_update_normalizes_numeric_values(tmp_path):
    db = TenderDatabase(tmp_path / "criteria.db")
    store = CriteriaStore(db)

    store.update("u1", min_price=10, max_price=20, min_advance_percent=15, min_submission_days=0, min_ai_score=80)
    criteria = store.get("u1")

    assert criteria.min_price == 10
    assert criteria.max_price == 20
    assert criteria.min_advance_percent == 15
    assert criteria.min_submission_days == 0
    assert criteria.min_ai_score == 80
