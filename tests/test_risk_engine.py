from datetime import datetime, timedelta, timezone

from src.models.tender import Tender
from src.risk.engine import RiskAssessment, RiskEngine


def _base_tender(**overrides) -> Tender:
    defaults = dict(platform="eis", external_id="1", title="Поставка подшипников", url="https://example.test/1", price=500000.0, customer="ООО Заказчик", region="Москва", deadline=datetime.now(timezone.utc) + timedelta(days=20), detail_status="success")
    defaults.update(overrides)
    return Tender(**defaults)


def test_clean_tender_is_low_risk_with_no_factors():
    assessment = RiskEngine().assess(_base_tender())
    assert isinstance(assessment, RiskAssessment)
    assert assessment.level == "LOW"
    assert assessment.factors == []


def test_all_critical_fields_missing_is_unknown():
    assessment = RiskEngine().assess(_base_tender(price=None, customer="", deadline=None))
    assert assessment.level == "UNKNOWN"
    assert "insufficient_data" in assessment.factor_codes


def test_partial_missing_data_is_medium_not_unknown():
    assessment = RiskEngine().assess(_base_tender(price=None))
    assert assessment.level == "MEDIUM"
    factor = next(f for f in assessment.factors if f.code == "insufficient_data")
    assert factor.severity == "medium"
    assert factor.source == "tender"
    assert "price" in factor.evidence


def test_naive_now_is_normalized_before_aware_deadline_comparison():
    now = datetime(2026, 9, 18, 12, 0)
    tender = _base_tender(deadline=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc))

    assessment = RiskEngine().assess(tender, now=now)

    assert assessment.level == "MEDIUM"
    assert "short_deadline" in assessment.factor_codes


def test_deadline_within_three_days_is_high():
    assessment = RiskEngine().assess(_base_tender(deadline=datetime.now(timezone.utc) + timedelta(days=2)))
    assert assessment.level == "HIGH"
    factor = next(f for f in assessment.factors if f.code == "short_deadline")
    assert factor.severity == "high"
    assert factor.source == "deadline"


def test_deadline_within_seven_days_is_medium():
    assessment = RiskEngine().assess(_base_tender(deadline=datetime.now(timezone.utc) + timedelta(days=5)))
    assert assessment.level == "MEDIUM"
    assert next(f for f in assessment.factors if f.code == "short_deadline").severity == "medium"


def test_deadline_already_passed_is_high():
    assessment = RiskEngine().assess(_base_tender(deadline=datetime.now(timezone.utc) - timedelta(days=1)))
    assert assessment.level == "HIGH"
    assert "deadline_passed" in assessment.factor_codes


def test_high_application_security_is_medium():
    assessment = RiskEngine().assess(_base_tender(application_security_percent=12.0))
    assert assessment.level == "MEDIUM"
    assert next(f for f in assessment.factors if f.code == "high_application_security").evidence == "12.0%"


def test_high_contract_security_is_medium():
    assessment = RiskEngine().assess(_base_tender(contract_security_percent=45.0))
    assert assessment.level == "MEDIUM"
    assert "high_contract_security" in assessment.factor_codes


def test_unclear_advance_is_low_severity_factor():
    assessment = RiskEngine().assess(_base_tender(advance_required=True, advance_percent=None))
    assert assessment.level == "LOW"
    assert next(f for f in assessment.factors if f.code == "unclear_advance").severity == "low"


def test_incomplete_detail_status_is_medium():
    assessment = RiskEngine().assess(_base_tender(detail_status="partial"))
    assert assessment.level == "MEDIUM"
    assert "incomplete_detail_data" in assessment.factor_codes


def test_worst_severity_wins_when_multiple_factors_present():
    assessment = RiskEngine().assess(_base_tender(detail_status="partial", deadline=datetime.now(timezone.utc) + timedelta(days=1)))
    assert assessment.level == "HIGH"
    assert {"incomplete_detail_data", "short_deadline"}.issubset(set(assessment.factor_codes))


def test_assessment_serializes_to_dict():
    assessment = RiskEngine().assess(_base_tender(application_security_percent=10.0))
    payload = assessment.to_dict()
    assert payload["level"] == "MEDIUM"
    assert payload["factors"][0]["code"] == "high_application_security"
    assert set(payload["factors"][0].keys()) == {"code", "severity", "evidence", "source", "explanation"}


def test_assessment_is_deterministic_for_same_input():
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    tender = _base_tender(deadline=now + timedelta(days=2))
    engine = RiskEngine()
    first = engine.assess(tender, now=now)
    second = engine.assess(tender, now=now)
    assert first.level == second.level
    assert first.factor_codes == second.factor_codes
