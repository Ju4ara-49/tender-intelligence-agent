from src.risk.engine import RiskAssessment, RiskEngine, RiskFactor
from src.risk.storage import RiskAssessmentStore


def test_risk_modules_import():
    assert RiskEngine is not None
    assert RiskAssessment is not None
    assert RiskFactor is not None
    assert RiskAssessmentStore is not None
