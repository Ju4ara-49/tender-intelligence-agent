from src.models.tender import Tender
from src.profiles import SearchProfile
from src.web_ui import profile_from_form, render_form


def test_web_form_matches_canonical_profile_fields():
    form = {
        "name": ["Оргтехника"],
        "keywords": ["принтеры, МФУ"],
        "exclusions": ["картриджи, ремонт"],
        "platforms": ["b2b_center", "fabrikant", "unknown"],
        "regions": ["Санкт-Петербург, Ленинградская область"],
        "min_price": ["100000"], "max_price": ["2000000"],
        "advance_required": ["1"], "min_advance_percent": ["30"],
        "max_postpayment_days": ["45"], "min_submission_days": ["7"],
        "min_application_security_percent": ["0"], "max_application_security_percent": ["5"],
        "min_contract_security_percent": ["0"], "max_contract_security_percent": ["10"],
        "min_ai_score": ["80"],
        "customer": ["ООО Ромашка"],
        "customer_inn": ["7701234567"],
        "law_type": ["44-ФЗ"],
        "document_search": ["1"],
    }
    p = profile_from_form(form, "u")
    assert p.user_id == "u"
    assert p.name == "Оргтехника"
    assert p.keywords == ["принтеры", "МФУ"]
    assert p.exclusions == ["картриджи", "ремонт"]
    assert p.platforms == ["b2b_center", "fabrikant"]
    assert p.regions == ["Санкт-Петербург", "Ленинградская область"]
    assert p.min_price == 100000
    assert p.max_price == 2000000
    assert p.advance_required is True
    assert p.min_advance_percent == 30
    assert p.max_postpayment_days == 45
    assert p.max_application_security_percent == 5
    assert p.max_contract_security_percent == 10
    assert p.min_ai_score == 80
    assert p.customer == "ООО Ромашка"
    assert p.customer_inn == "7701234567"
    assert p.law_type == "44-ФЗ"
    assert p.document_search is True


def test_web_render_is_russian_and_escapes_user_values():
    profile = SearchProfile(name='<script>alert(1)</script>', keywords=['подшипники'])
    page = render_form(profile)
    assert 'Добавление нового ключа' in page
    assert 'Ключевые слова' in page
    assert 'Площадки' in page
    assert '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page


def test_web_form_defaults_match_product_search_defaults():
    p = profile_from_form({"name": ["Тест"], "keywords": ["подшипники"]})
    assert p.min_submission_days == 7
    assert p.min_ai_score == 70
    assert p.advance_required is False
    assert p.document_search is False
    assert p.customer is None
    assert p.customer_inn is None
    assert p.law_type is None


def test_web_form_document_search_checkbox_is_not_disabled():
    profile = SearchProfile(name="Test", document_search=True)
    page = render_form(profile)
    assert 'name="document_search"' in page
    assert 'disabled' not in page.split('document_search')[1][:200]


def test_web_form_contains_new_filter_fields():
    page = render_form(SearchProfile())
    assert 'name="customer"' in page
    assert 'name="customer_inn"' in page
    assert 'name="law_type"' in page
