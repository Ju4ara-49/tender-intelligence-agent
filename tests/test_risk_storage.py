from datetime import datetime, timedelta, timezone
import sqlite3

from src.models.tender import Tender
from src.risk.engine import RiskEngine
from src.risk.storage import RiskAssessmentStore


def _db_with_tender(tmp_path):
    db_path = tmp_path / "risk.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE tenders (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL
        )
        """
    )
    conn.execute("INSERT INTO tenders (id, title) VALUES (1, 'test')")
    conn.commit()
    conn.close()
    return db_path


def _tender():
    return Tender(
        platform="eis",
        external_id="1",
        title="Поставка подшипников",
        url="https://example.test/1",
        price=500000,
        customer="ООО Заказчик",
        deadline=datetime.now(timezone.utc) + timedelta(days=2),
        detail_status="success",
    )


def test_save_and_get_round_trip(tmp_path):
    store = RiskAssessmentStore(_db_with_tender(tmp_path))
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    assessment = RiskEngine().assess(_tender(), now=now)

    store.save(1, assessment, assessed_at=now)
    restored = store.get(1)

    assert restored is not None
    assert restored.level == "HIGH"
    assert restored.factor_codes == ["short_deadline"]
    assert restored.factors[0].source == "deadline"


def test_save_replaces_previous_assessment(tmp_path):
    store = RiskAssessmentStore(_db_with_tender(tmp_path))
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    first = RiskEngine().assess(_tender(), now=now)
    second = RiskEngine().assess(_tender(application_security_percent=10), now=now)

    store.save(1, first, assessed_at=now)
    store.save(1, second, assessed_at=now)

    restored = store.get(1)
    assert restored is not None
    assert restored.level == "HIGH"
    assert "short_deadline" in restored.factor_codes
    assert "high_application_security" in restored.factor_codes


def test_get_missing_returns_none(tmp_path):
    store = RiskAssessmentStore(_db_with_tender(tmp_path))
    assert store.get(999) is None
