from datetime import datetime, timedelta, timezone

from src.models.tender import Tender
from src.risk.engine import RiskAssessment, RiskEngine


def _base_tender(**overrides) -> Tender:
    defaults = dict(
        platform="eis",
        external_id="1",
        title="Поставка подшипников",
        url="https://example.test/1",
        price=500000.0,
        customer="ООО Заказчик",
        region="Москва",
        deadline=datetime.now(timezone.utc) + timedelta(days=20),
        detail_status="success",
    )
    defaults.update(overrides)
    return Tender(**defaults)


def test_clean_tender_is_low_risk_with_no_factors():
    engine = RiskEngine()
    tender = _base_tender()

    assessment = engine.assess(tender)

    assert isinstance(assessment, RiskAssessment)
    assert assessment.level == "LOW"
    assert assessment.factors == []


def test_all_critical_fields_missing_is_unknown():
    engine = RiskEngine()
    tender = _base_tender(price=None, customer="", deadline=None)

    assessment = engine.assess(tender)

    assert assessment.level == "UNKNOWN"
    assert "insufficient_data" in assessment.factor_codes


def test_partial_missing_data_is_medium_not_unknown():
    engine = RiskEngine()
    tender = _base_tender(price=None)

    assessment = engine.assess(tender)

    assert assessment.level == "MEDIUM"
    factor = next(f for f in assessment.factors if f.code == "insufficient_data")
    assert factor.severity == "medium"
    assert factor.source == "tender"
    assert "price" in factor.evidence


def test_deadline_within_three_days_is_high():
    engine = RiskEngine()
    tender = _base_tender(deadline=datetime.now(timezone.utc) + timedelta(days=2))

    assessment = engine.assess(tender)

    assert assessment.level == "HIGH"
    factor = next(f for f in assessment.factors if f.code == "short_deadline")
    assert factor.severity == "high"
    assert factor.source == "deadline"


def test_deadline_within_seven_days_is_medium():
    engine = RiskEngine()
    tender = _base_tender(deadline=datetime.now(timezone.utc) + timedelta(days=5))

    assessment = engine.assess(tender)

    assert assessment.level == "MEDIUM"
    factor = next(f for f in assessment.factors if f.code == "short_deadline")
    assert factor.severity == "medium"


def test_deadline_already_passed_is_high():
    engine = RiskEngine()
    tender = _base_tender(deadline=datetime.now(timezone.utc) - timedelta(days=1))

    assessment = engine.assess(tender)

    assert assessment.level == "HIGH"
    assert "deadline_passed" in assessment.factor_codes


def test_high_application_security_is_medium():
    engine = RiskEngine()
    tender = _base_tender(application_security_percent=12.0)

    assessment = engine.assess(tender)

    assert assessment.level == "MEDIUM"
    factor = next(f for f in assessment.factors if f.code == "high_application_security")
    assert factor.evidence == "12.0%"


def test_high_contract_security_is_medium():
    engine = RiskEngine()
    tender = _base_tender(contract_security_percent=45.0)

    assessment = engine.assess(tender)

    assert assessment.level == "MEDIUM"
    assert "high_contract_security" in assessment.factor_codes


def test_unclear_advance_is_low_severity_factor():
    engine = RiskEngine()
    tender = _base_tender(advance_required=True, advance_percent=None)

    assessment = engine.assess(tender)

    assert assessment.level == "LOW"
    factor = next(f for f in assessment.factors if f.code == "unclear_advance")
    assert factor.severity == "low"


def test_incomplete_detail_status_is_medium():
    engine = RiskEngine()
    tender = _base_tender(detail_status="partial")

    assessment = engine.assess(tender)

    assert assessment.level == "MEDIUM"
    assert "incomplete_detail_data" in assessment.factor_codes


def test_worst_severity_wins_when_multiple_factors_present():
    engine = RiskEngine()
    tender = _base_tender(
        detail_status="partial",
        deadline=datetime.now(timezone.utc) + timedelta(days=1),
    )

    assessment = engine.assess(tender)

    assert assessment.level == "HIGH"
    assert {"incomplete_detail_data", "short_deadline"}.issubset(set(assessment.factor_codes))


def test_assessment_serializes_to_dict():
    engine = RiskEngine()
    tender = _base_tender(application_security_percent=10.0)

    assessment = engine.assess(tender)
    payload = assessment.to_dict()

    assert payload["level"] == "MEDIUM"
    assert payload["factors"][0]["code"] == "high_application_security"
    assert set(payload["factors"][0].keys()) == {"code", "severity", "evidence", "source", "explanation"}


def test_assessment_is_deterministic_for_same_input():
    engine = RiskEngine()
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    tender = _base_tender(deadline=now + timedelta(days=2))

    first = engine.assess(tender, now=now)
    second = engine.assess(tender, now=now)

    assert first.level == second.level
    assert first.factor_codes == second.factor_codes
