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


def test_owner_identity_is_configurable_and_whitelist_path_is_project_root(monkeypatch, tmp_path):
    import src.telegram_multiuser as module
    from src.telegram_multiuser import MultiUserTelegramBot

    monkeypatch.setenv("TELEGRAM_OWNER_USER_ID", "owner-42")
    bot = object.__new__(MultiUserTelegramBot)
    bot.owner_telegram_id = "owner-42"
    bot._allowed_user_ids = {"owner-42", "123"}
    assert bot._is_owner("owner-42")
    assert not bot._is_owner("838120236")

    whitelist = tmp_path / "data" / "telegram_allowed_users.json"
    monkeypatch.setattr(module, "WHITELIST_FILE", whitelist)
    bot._save_allowed_user_ids()
    assert whitelist.exists()
    assert "owner-42" not in whitelist.read_text(encoding="utf-8")
    assert "123" in whitelist.read_text(encoding="utf-8")


def test_owner_user_list_uses_instance_owner_identity_and_escapes_ids(monkeypatch):
    from src.telegram_multiuser import MultiUserTelegramBot

    bot = object.__new__(MultiUserTelegramBot)
    bot.owner_telegram_id = "owner-42"
    bot._allowed_user_ids = {"owner-42", "123&456"}
    sent = []
    bot._send = lambda chat_id, text, reply_markup=None: sent.append((chat_id, text, reply_markup))
    bot._admin_keyboard = lambda: {"keyboard": []}

    bot._show_users("owner-42")

    assert len(sent) == 1
    assert "owner-42" in sent[0][1]
    assert "— владелец" in sent[0][1]
    assert "123&amp;456" in sent[0][1]
