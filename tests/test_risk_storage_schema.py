import sqlite3

from src.risk.storage import RiskAssessmentStore


def test_store_creates_expected_schema(tmp_path):
    db_path = tmp_path / "schema.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE tenders (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
    conn.commit()
    conn.close()

    RiskAssessmentStore(db_path)
    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(risk_assessments)")}
    conn.close()

    assert columns == {"tender_id", "level", "factors", "assessed_at"}
