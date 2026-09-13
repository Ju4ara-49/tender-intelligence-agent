from src.profiles import SearchProfile
from src.storage.database import TenderDatabase
from src.telegram_full_criteria import BTN_EXCLUDE, BTN_PROFILES, BTN_REGIONS, FullCriteriaTelegramBot
from src.telegram_settings import CriteriaStore


def test_user_regions_and_exclusions_are_persisted(tmp_path):
    db = TenderDatabase(tmp_path / "criteria.db")
    store = CriteriaStore(db)

    store.set_regions("user-1", [" Санкт-Петербург ", "Москва", "Москва"])
    store.set_exclude_keywords("user-1", ["строительство", "РЕМОНТ", "ремонт"])

    assert store.get_regions("user-1") == ["Санкт-Петербург", "Москва"]
    assert store.get_exclude_keywords("user-1") == ["строительство", "РЕМОНТ"]
    assert store.get_regions("user-2") == []
    assert store.get_exclude_keywords("user-2") == []


def test_old_criteria_table_migrates_without_regions_or_exclusions(tmp_path):
    db_path = tmp_path / "legacy.db"
    db = TenderDatabase(db_path)
    with db._connect() as conn:
        conn.execute(
            """
            CREATE TABLE tender_settings (
                id INTEGER PRIMARY KEY,
                min_price REAL,
                max_price REAL,
                advance_required INTEGER,
                min_advance_percent REAL,
                max_postpayment_days INTEGER,
                min_submission_days INTEGER,
                min_application_security_percent REAL,
                max_application_security_percent REAL,
                min_contract_security_percent REAL,
                max_contract_security_percent REAL,
                min_ai_score INTEGER,
                keywords TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO tender_settings VALUES (1, NULL, NULL, 0, 0, NULL, 7, 0, 5, 0, NULL, 70, '[]', 'now')"
        )
    store = CriteriaStore(db)

    criteria = store.get("legacy-user")
    assert criteria.min_submission_days == 7
    assert criteria.max_application_security_percent == 5
    assert store.get_regions("legacy-user") == []
    assert store.get_exclude_keywords("legacy-user") == []


def test_full_criteria_keyboard_contains_region_exclusion_and_profile_controls():
    keyboard = FullCriteriaTelegramBot._keyboard()
    texts = {button["text"] for row in keyboard["keyboard"] for button in row}
    assert BTN_REGIONS in texts
    assert BTN_EXCLUDE in texts
    assert BTN_PROFILES in texts


def test_profile_keyboards_are_crud_safe_and_use_bounded_callback_ids():
    profiles = [SearchProfile(id=7, user_id="u", name="Подшипники", enabled=True)]
    listing = FullCriteriaTelegramBot._profiles_keyboard(profiles)
    callbacks = [button["callback_data"] for row in listing["inline_keyboard"] for button in row]
    assert "profiles:open:7" in callbacks
    assert "profiles:create" in callbacks
    assert "profiles:close" in callbacks
    assert all(len(value) <= 64 for value in callbacks)

    editor = FullCriteriaTelegramBot._profile_edit_keyboard(7)
    edit_callbacks = [button["callback_data"] for row in editor["inline_keyboard"] for button in row]
    assert "profiles:edit:7:name" in edit_callbacks
    assert "profiles:edit:7:keywords" in edit_callbacks
    assert "profiles:toggle:7" in edit_callbacks
    assert "profiles:duplicate:7" in edit_callbacks
    assert "profiles:delete:7" in edit_callbacks
    assert all(len(value) <= 64 for value in edit_callbacks)
