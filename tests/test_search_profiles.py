from src.profiles import SearchProfile, SearchProfileStore
from src.storage.database import TenderDatabase
from src.telegram_settings import CriteriaStore


def test_profile_crud_and_user_isolation(tmp_path):
    db = TenderDatabase(tmp_path / "profiles.sqlite3")
    store = SearchProfileStore(db)

    first = store.create("user-a", name="Подшипники", keywords=["подшипники"], platforms=["eis"], min_price=100000)
    second = store.create("user-b", name="Муфты", keywords=["муфты"], platforms=["b2b_center"])

    assert store.get("user-a", first.id).keywords == ["подшипники"]
    assert store.get("user-a", second.id) is None
    assert [p.name for p in store.list("user-b")] == ["Муфты"]

    updated = store.update("user-a", first.id, max_price=500000, enabled=False)
    assert updated.max_price == 500000
    assert not updated.enabled

    duplicate = store.duplicate("user-a", first.id, "Подшипники копия")
    assert duplicate.id != first.id
    assert duplicate.name == "Подшипники копия"

    store.delete("user-a", duplicate.id)
    assert store.get("user-a", duplicate.id) is None


def test_default_profile_migrates_real_criteria(tmp_path):
    db = TenderDatabase(tmp_path / "profiles.sqlite3")
    criteria = CriteriaStore(db)
    criteria.update("user-a", min_price=100000, max_price=2000000, min_ai_score=85)
    criteria.set_keywords("user-a", ["подшипники"])
    criteria.set_enabled_platforms("user-a", ["eis", "rosatom"])

    store = SearchProfileStore(db)
    profile = store.ensure_default_profile("user-a", criteria)

    assert profile.name == "Основной"
    assert profile.keywords == ["подшипники"]
    assert profile.platforms == ["eis", "rosatom"]
    assert profile.min_price == 100000
    assert profile.max_price == 2000000
    assert profile.min_ai_score == 85


def test_profile_stats_are_derived_from_recorded_runs(tmp_path):
    db = TenderDatabase(tmp_path / "profiles.sqlite3")
    store = SearchProfileStore(db)
    profile = store.create("user-a", SearchProfile(name="Тест"))

    store.record_run("user-a", profile.id, {"search_number": 1, "found": 10, "filtered": 4, "new": 2, "analyzed": 2, "notified": 1, "skipped_duplicate": 3, "excluded_by_criteria": 3})
    store.record_run("user-a", profile.id, {"search_number": 2, "found": 5, "filtered": 2, "new": 1, "analyzed": 1, "notified": 1, "skipped_duplicate": 1, "excluded_by_criteria": 2})

    stats = store.stats("user-a", profile.id)
    assert stats["runs"] == 2
    assert stats["found"] == 15
    assert stats["filtered"] == 6
    assert stats["new_count"] == 3
    assert stats["notified"] == 2
