from datetime import datetime, timedelta, timezone
from src.models.tender import Tender
from src.risk.engine import RiskEngine

def tender(**kw):
    d=dict(platform="eis", external_id="1", title="Поставка", url="https://x", price=100,
           customer="Заказчик", deadline=datetime(2026,9,18,12,tzinfo=timezone.utc)+timedelta(days=20),
           detail_status="success")
    d.update(kw); return Tender(**d)

def test_clean_is_low():
    a=RiskEngine().assess(tender()); assert a.level=="LOW" and not a.factors

def test_missing_critical_is_unknown():
    a=RiskEngine().assess(tender(price=None, customer="", deadline=None)); assert a.level=="UNKNOWN"

def test_short_deadline_high():
    a=RiskEngine().assess(tender(deadline=datetime(2026,9,19,12,tzinfo=timezone.utc)), now=datetime(2026,9,18,12,tzinfo=timezone.utc))
    assert a.level=="HIGH" and "short_deadline" in a.factor_codes

def test_security_and_advance_factors():
    a=RiskEngine().assess(tender(application_security_percent=10, contract_security_percent=40, advance_required=True))
    assert a.level=="MEDIUM"
    assert {"high_application_security","high_contract_security","unclear_advance"} <= set(a.factor_codes)

def test_serialization_is_stable():
    a=RiskEngine().assess(tender(application_security_percent=10)).to_dict()
    assert a["level"]=="MEDIUM" and set(a["factors"][0])=={"code","severity","evidence","source","explanation"}
