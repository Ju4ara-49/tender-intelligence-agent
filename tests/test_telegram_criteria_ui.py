from src.telegram_criteria_multiuser import CriteriaAwareResponsiveTelegramBot


def test_criteria_keyboard_contains_all_commercial_filters():
    labels = [cell["text"] for row in CriteriaAwareResponsiveTelegramBot._keyboard()["keyboard"] for cell in row]
    assert "Аванс" in labels
    assert "Постоплата до:" in labels
    assert "Обеспечение заявки до:" in labels
    assert "Обеспечение контракта до:" in labels


def test_criteria_labels_are_stable():
    assert CriteriaAwareResponsiveTelegramBot._label("min_advance_percent") == "Аванс от"
    assert CriteriaAwareResponsiveTelegramBot._label("max_postpayment_days") == "Постоплата до"
    assert CriteriaAwareResponsiveTelegramBot._label("max_application_security_percent") == "Обеспечение заявки до"
    assert CriteriaAwareResponsiveTelegramBot._label("max_contract_security_percent") == "Обеспечение контракта до"
