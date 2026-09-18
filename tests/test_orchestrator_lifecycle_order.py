from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.models.tender import Tender, TenderAnalysis
from src.orchestrator import Orchestrator
from src.tenderplan import TenderLifecycleStatus, TenderLifecycleStore, TenderTaskStore

def _obj(tmp_path: Path):
    obj=Orchestrator.__new__(Orchestrator)
    obj.task_store=TenderTaskStore(tmp_path/"agent.db")
    obj.lifecycle_store=TenderLifecycleStore(tmp_path/"agent.db")
    obj.notifier=SimpleNamespace()
    return obj

def _tender():
    return Tender(platform="eis", external_id="1", title="Поставка", url="https://x",
                  customer="Заказчик", price=100, deadline=datetime(2026,10,1,tzinfo=timezone.utc))

def test_lifecycle_relevance_precedes_shortlist(tmp_path: Path):
    obj=_obj(tmp_path); tender=_tender()
    obj.lifecycle_store.ensure(tender.unique_key)
    obj._advance_lifecycle(tender, TenderLifecycleStatus.RELEVANT)
    assert obj.lifecycle_store.get(tender.unique_key) is TenderLifecycleStatus.RELEVANT
    obj._advance_lifecycle(tender, TenderLifecycleStatus.SHORTLISTED)
    assert obj.lifecycle_store.get(tender.unique_key) is TenderLifecycleStatus.SHORTLISTED

def test_low_ai_score_does_not_shortlist(tmp_path: Path):
    obj=_obj(tmp_path); tender=_tender()
    obj.lifecycle_store.ensure(tender.unique_key)
    analysis=TenderAnalysis(relevance_score=10, summary="", recommendation="skip")
    assert analysis.relevance_score < 70
    obj._advance_lifecycle(tender, TenderLifecycleStatus.RELEVANT)
    assert obj.lifecycle_store.get(tender.unique_key) is TenderLifecycleStatus.RELEVANT
