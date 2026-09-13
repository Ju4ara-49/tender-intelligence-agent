import pytest

from src.telegram_settings import TenderCriteria


def test_advance_required_rejects_string_false_instead_of_coercing_to_true():
    with pytest.raises(ValueError, match="advance_required"):
        TenderCriteria(advance_required="false")


def test_advance_required_accepts_real_booleans():
    assert TenderCriteria(advance_required=False).advance_required is False
    assert TenderCriteria(advance_required=True).advance_required is True
