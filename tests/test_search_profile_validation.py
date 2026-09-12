import pytest

from src.profiles import SearchProfile, SearchProfileStore
from src.storage.database import TenderDatabase


def test_search_profile_rejects_invalid_criteria_at_model_boundary():
    with pytest.raises(ValueError):
        SearchProfile(min_price=1000, max_price=100)
    with pytest.raises(ValueError):
        SearchProfile(min_ai_score=101)
    with pytest.raises(ValueError):
        SearchProfile(min_submission_days=-1)
    with pytest.raises(ValueError):
        SearchProfile(min_application_security_percent=6, max_application_security_percent=5)


def test_search_profile_store_create_validates_after_profile_mutation(tmp_path):
    db = TenderDatabase(tmp_path / "profiles.db")
    store = SearchProfileStore(db)
    profile = SearchProfile(user_id="u1")
    profile.min_price = 1000
    profile.max_price = 100

    with pytest.raises(ValueError):
        store.create("u1", profile)

    assert store.list("u1") == []


def test_search_profile_store_update_validates_merged_state_without_partial_write(tmp_path):
    db = TenderDatabase(tmp_path / "profiles.db")
    store = SearchProfileStore(db)
    profile = store.create("u1", min_price=100, max_price=1000, min_ai_score=80)

    with pytest.raises(ValueError):
        store.update("u1", profile.id, min_price=2000)

    current = store.get("u1", profile.id)
    assert current is not None
    assert current.min_price == 100
    assert current.max_price == 1000
    assert current.min_ai_score == 80


def test_search_profile_store_update_normalizes_lists_and_preserves_valid_state(tmp_path):
    db = TenderDatabase(tmp_path / "profiles.db")
    store = SearchProfileStore(db)
    profile = store.create("u1")

    updated = store.update(
        "u1",
        profile.id,
        exclusions=[" А ", "а", ""],
        regions=[" СПб ", "спб"],
        min_price=0,
        max_price=100,
        min_submission_days=0,
        min_ai_score=100,
    )

    assert updated.exclusions == ["А"]
    assert updated.regions == ["СПб"]
    assert updated.min_price == 0
    assert updated.max_price == 100
    assert updated.min_submission_days == 0
    assert updated.min_ai_score == 100


def test_search_profile_model_rejects_non_bool_enabled():
    with pytest.raises(ValueError):
        SearchProfile(enabled="false")
