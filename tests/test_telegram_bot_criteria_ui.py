from types import SimpleNamespace

from src.telegram_bot import TelegramBot


class FakeCriteriaStore:
    def __init__(self):
        self.values = {
            "min_price": None,
            "max_price": None,
            "advance_required": False,
            "min_advance_percent": 0.0,
            "max_postpayment_days": None,
            "min_submission_days": 7,
            "min_application_security_percent": 0.0,
            "max_application_security_percent": 5.0,
            "min_contract_security_percent": 0.0,
            "max_contract_security_percent": None,
            "min_ai_score": 70,
        }
        self.keywords = []
        self.exclusions = []
        self.regions = []
        self.platforms = ["eis", "b2b_center", "fabrikant", "rts_tender", "tmk", "rosatom"]

    def update(self, user_id, **values):
        self.values.update(values)

    def set_keywords(self, user_id, values):
        self.keywords = list(values)

    def get_keywords(self, user_id):
        return list(self.keywords)

    def set_exclude_keywords(self, user_id, values):
        self.exclusions = list(values)

    def get_exclude_keywords(self, user_id):
        return list(self.exclusions)

    def set_regions(self, user_id, values):
        self.regions = list(values)

    def get_regions(self, user_id):
        return list(self.regions)

    def get_enabled_platforms(self, user_id):
        return list(self.platforms)

    def set_enabled_platforms(self, user_id, values):
        self.platforms = list(values)

    def get(self, user_id):
        return SimpleNamespace(**self.values)


def _bot():
    bot = TelegramBot.__new__(TelegramBot)
    bot.criteria_store = FakeCriteriaStore()
    bot._waiting_for = {}
    bot._search_threads = {}
    bot._search_orchestrators = {}
    bot._send = lambda *args, **kwargs: None
    return bot


def test_keyboard_exposes_all_required_search_filters():
    keyboard = TelegramBot._keyboard()["keyboard"]
    labels = {item["text"] for row in keyboard for item in row}
    assert {
        "Цена от:", "Цена до:", "Аванс", "Постоплата", "Обеспечение заявки",
        "Обеспечение контракта", "Срок:", "Балл:", "Регионы", "Ключевые слова",
        "Исключающие слова", "Площадки", "Поиск", "Настройки", "Стоп",
    } <= labels


def test_advance_flow_saves_required_flag_then_minimum_percent():
    bot = _bot()
    bot._waiting_for["42"] = "advance_required"

    assert bot._handle_value_input("42", "да") is True
    assert bot.criteria_store.values["advance_required"] is True
    assert bot._waiting_for["42"] == "min_advance_percent"

    assert bot._handle_value_input("42", "30") is True
    assert bot.criteria_store.values["min_advance_percent"] == 30.0
    assert "42" not in bot._waiting_for


def test_list_filters_are_saved_per_user():
    bot = _bot()
    for field, value in (
        ("regions", "Москва, Санкт-Петербург"),
        ("exclude_keywords", "мебель, продукты питания"),
        ("keywords", "подшипники, запасные части"),
    ):
        bot._waiting_for["42"] = field
        assert bot._handle_value_input("42", value) is True

    assert bot.criteria_store.regions == ["Москва", "Санкт-Петербург"]
    assert bot.criteria_store.exclusions == ["мебель", "продукты питания"]
    assert bot.criteria_store.keywords == ["подшипники", "запасные части"]


def test_invalid_cross_field_criteria_is_reported_without_losing_input_state():
    bot = _bot()
    bot._waiting_for["42"] = "max_price"

    def reject(*args, **kwargs):
        raise ValueError("min_price cannot exceed max_price")

    bot.criteria_store.update = reject
    assert bot._handle_value_input("42", "100000") is True
    assert bot._waiting_for["42"] == "max_price"
