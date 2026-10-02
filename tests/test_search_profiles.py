from src.profiles import SearchProfile, SearchProfileStore
from src.storage.database import TenderDatabase
from src.telegram_settings import CriteriaStore

import pytest


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


def test_default_profile_copies_contract_criteria(tmp_path):
    db = TenderDatabase(tmp_path / "profiles_contract_default.sqlite3")
    criteria = CriteriaStore(db)
    criteria.update(
        "user-a",
        okpd2_codes=["01.11"],
        procurement_types=["bankruptcy_property"],
        document_search=True,
    )

    profile = SearchProfileStore(db).ensure_default_profile("user-a", criteria)

    assert profile.okpd2_codes == ["01.11"]
    assert profile.procurement_types == ["bankruptcy_property"]
    assert profile.document_search is True


def test_legacy_criteria_controls_sync_existing_default_profile(tmp_path):
    db = TenderDatabase(tmp_path / "profiles_legacy_sync.sqlite3")
    criteria = CriteriaStore(db)
    store = SearchProfileStore(db)
    profile = store.create("user-a", SearchProfile(name="Основной", keywords=["старое"]))

    criteria.set_keywords("user-a", ["новое"])
    criteria.update("user-a", min_price=100000, min_submission_days=9)
    criteria.set_regions("user-a", ["Москва"])

    loaded = store.get("user-a", profile.id)
    assert loaded.keywords == ["новое"]
    assert loaded.min_price == 100000
    assert loaded.min_submission_days == 9
    assert loaded.regions == ["Москва"]


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



def test_profile_search_uses_user_scoped_delivery_and_aggregates_results(monkeypatch, tmp_path):
    db = TenderDatabase(tmp_path / "profiles.sqlite3")
    store = SearchProfileStore(db)
    first = store.create("user-a", name="Первый", keywords=["один"])
    second = store.create("user-a", name="Второй", keywords=["два"])

    from src.orchestrator import Orchestrator
    from src.models.tender import Tender

    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.profile_store = store
    orchestrator.criteria_store = CriteriaStore(db)
    orchestrator._stop_requested = False
    tender_a = Tender(platform="eis", external_id="A", title="A", url="https://example.test/a")
    tender_b = Tender(platform="eis", external_id="B", title="B", url="https://example.test/b")
    calls = []

    def fake_run_cycle(**kwargs):
        calls.append(kwargs["notification_recipient_key"])
        orchestrator.last_run_results = [tender_a] if len(calls) == 1 else [tender_a, tender_b]
        return {"search_number": len(calls), "found": 2, "filtered": 2, "new": 2, "analyzed": 2, "notified": 1, "skipped_duplicate": 0, "excluded_by_criteria": 0}

    monkeypatch.setattr(orchestrator, "run_cycle", fake_run_cycle)
    results = orchestrator.run_cycle_for_user("user-a")

    assert results and len(results) == 2
    assert calls == ["user:user-a", "user:user-a"]
    assert [t.unique_key for t in orchestrator.last_run_results] == ["eis:A", "eis:B"]
    assert store.stats("user-a", first.id)["runs"] == 1
    assert store.stats("user-a", second.id)["runs"] == 1



def test_profile_store_rejects_impossible_ranges(tmp_path):
    db = TenderDatabase(tmp_path / "profiles.db")
    store = SearchProfileStore(db)
    try:
        store.create("u", name="bad", min_price=100, max_price=50)
        assert False, "expected invalid price range to be rejected"
    except ValueError as exc:
        assert "min_price" in str(exc)

    profile = store.create("u", name="good", min_price=100, max_price=200)
    try:
        store.update("u", profile.id, max_price=50)
        assert False, "expected update to reject invalid range"
    except ValueError as exc:
        assert "min_price" in str(exc)

    assert store.get("u", profile.id).max_price == 200



def test_profile_store_rejects_negative_and_nonfinite_numeric_values(tmp_path):
    import math
    db = TenderDatabase(tmp_path / "profiles_numeric.db")
    store = SearchProfileStore(db)
    for kwargs in ({"min_price": -1}, {"max_price": -1}, {"min_advance_percent": math.nan}, {"min_ai_score": 101}):
        try:
            store.create("u", name="bad-" + str(len(kwargs)), **kwargs)
            assert False, "expected invalid numeric profile value to be rejected"
        except ValueError:
            pass


def test_profile_store_persists_new_filter_fields(tmp_path):
    db = TenderDatabase(tmp_path / "profiles_newfields.sqlite3")
    store = SearchProfileStore(db)
    profile = store.create("user-a", SearchProfile(
        name="Новый", customer="ООО Ромашка", customer_inn="7701234567",
        law_type="44-ФЗ", document_search=True,
    ))
    loaded = store.get("user-a", profile.id)
    assert loaded.customer == "ООО Ромашка"
    assert loaded.customer_inn == "7701234567"
    assert loaded.law_type == "44-ФЗ"
    assert loaded.document_search is True


def test_profile_criteria_passes_new_filter_fields(tmp_path):
    db = TenderDatabase(tmp_path / "profiles_criteria.sqlite3")
    store = SearchProfileStore(db)
    profile = store.create("user-a", SearchProfile(
        name="Фильтры", customer="ООО Ромашка", customer_inn="7701234567",
        law_type="44-ФЗ",
    ))
    criteria = profile.criteria()
    assert criteria.customer == "ООО Ромашка"
    assert criteria.customer_inn == "7701234567"
    assert criteria.law_type == "44-ФЗ"


def test_profile_store_persists_contract_filters_okpd2_and_procurement_types(tmp_path):
    db = TenderDatabase(tmp_path / "profiles_contract.sqlite3")
    store = SearchProfileStore(db)
    profile = store.create("user-a", SearchProfile(
        name="Контрактные фильтры",
        okpd2_codes=["01.11.12", "26.30"],
        procurement_types=["plan_schedule", "bankruptcy_property"],
    ))
    loaded = store.get("user-a", profile.id)
    assert loaded.okpd2_codes == ["01.11.12", "26.30"]
    assert loaded.procurement_types == ["plan_schedule", "bankruptcy_property"]

    updated = store.update("user-a", profile.id, procurement_types=["commercial"], okpd2_codes=[" 01 "])
    assert updated.procurement_types == ["commercial"]
    assert updated.okpd2_codes == ["01"]


def test_profile_criteria_passes_contract_filters_to_canonical_criteria(tmp_path):
    db = TenderDatabase(tmp_path / "profiles_contract_criteria.sqlite3")
    store = SearchProfileStore(db)
    profile = store.create("user-a", SearchProfile(
        name="Контракт", okpd2_codes=["01.11"], procurement_types=["plan_schedule"],
    ))
    criteria = profile.criteria()
    assert criteria.okpd2_codes == ["01.11"]
    assert criteria.procurement_types == ["plan_schedule"]


def test_profile_store_rejects_invalid_contract_filter_values(tmp_path):
    db = TenderDatabase(tmp_path / "profiles_contract_bad.sqlite3")
    store = SearchProfileStore(db)
    with pytest.raises(ValueError, match="ОКПД2"):
        store.create("user-a", name="bad-okpd2", okpd2_codes=["мусор"])
    with pytest.raises(ValueError, match="режим"):
        store.create("user-a", name="bad-procurement", procurement_types=["lunar"])


def test_profile_store_backward_compatible_with_old_db(tmp_path):
    db = TenderDatabase(tmp_path / "profiles_old.sqlite3")
    store = SearchProfileStore(db)
    # Simulate old DB without new columns by creating a minimal table
    with db._connect() as conn:
        conn.execute("DROP TABLE IF EXISTS search_profiles")
        conn.execute("""
            CREATE TABLE search_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL, name TEXT NOT NULL, keywords TEXT NOT NULL DEFAULT '[]',
                exclusions TEXT NOT NULL DEFAULT '[]', platforms TEXT NOT NULL DEFAULT '[]',
                regions TEXT NOT NULL DEFAULT '[]', min_price REAL, max_price REAL,
                advance_required INTEGER NOT NULL DEFAULT 0, min_advance_percent REAL NOT NULL DEFAULT 0,
                max_postpayment_days INTEGER, min_submission_days INTEGER NOT NULL DEFAULT 7,
                min_application_security_percent REAL NOT NULL DEFAULT 0,
                max_application_security_percent REAL, min_contract_security_percent REAL NOT NULL DEFAULT 0,
                max_contract_security_percent REAL, min_ai_score INTEGER NOT NULL DEFAULT 70,
                enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(user_id, name)
            )
        """)
        # Should auto-migrate new columns
    store2 = SearchProfileStore(db)
    profile = store2.create("user-a", name="Test", keywords=["тест"])
    assert profile.id is not None
    loaded = store2.get("user-a", profile.id)
    assert loaded.document_search is False
    assert loaded.customer is None
