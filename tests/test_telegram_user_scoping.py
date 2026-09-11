from src.storage.database import TenderDatabase
from src.telegram_settings import CriteriaStore, SUPPORTED_PLATFORMS


def test_criteria_are_isolated_by_explicit_user_id(tmp_path):
    store = CriteriaStore(TenderDatabase(tmp_path / "settings.sqlite3"))

    store.update("user-a", min_price=100000, min_ai_score=80)
    store.update("user-b", min_price=900000, min_ai_score=60)
    store.set_keywords("user-a", ["подшипники"])
    store.set_keywords("user-b", ["муфты"])

    assert store.get("user-a").min_price == 100000
    assert store.get("user-a").min_ai_score == 80
    assert store.get_keywords("user-a") == ["подшипники"]

    assert store.get("user-b").min_price == 900000
    assert store.get("user-b").min_ai_score == 60
    assert store.get_keywords("user-b") == ["муфты"]


def test_platforms_are_isolated_and_use_current_names(tmp_path):
    store = CriteriaStore(TenderDatabase(tmp_path / "settings.sqlite3"))
    store.set_enabled_platforms("user-a", ["eis", "fabrikant", "rosatom"])
    store.set_enabled_platforms("user-b", ["b2b_center"])

    assert store.get_enabled_platforms("user-a") == ["eis", "fabrikant", "rosatom"]
    assert store.get_enabled_platforms("user-b") == ["b2b_center"]
    assert "unipro" not in SUPPORTED_PLATFORMS


def test_empty_user_id_uses_only_explicit_default_not_stack_introspection(tmp_path):
    store = CriteriaStore(TenderDatabase(tmp_path / "settings.sqlite3"))
    assert store.normalize_user_id(None) == "default"
    assert store.normalize_user_id("  ") == "default"
    assert store.normalize_user_id("12345") == "12345"
