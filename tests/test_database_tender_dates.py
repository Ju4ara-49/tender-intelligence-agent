from datetime import datetime, timezone
import sqlite3

from src.models.tender import Tender
from src.storage.database import TenderDatabase


def _tender(start=None, end=None):
    return Tender(
        platform="test",
        external_id="dates-1",
        title="Тест дат",
        url="https://example.test/dates-1",
        start_date=start,
        end_date=end,
        deadline=end,
        published_at=start,
    )


def test_start_and_end_dates_are_persisted_and_tracked(tmp_path):
    db = TenderDatabase(tmp_path / "dates.db")
    start = datetime(2026, 9, 12, 9, tzinfo=timezone.utc)
    end = datetime(2026, 9, 20, 18, tzinfo=timezone.utc)
    tender = _tender(start, end)
    tender_id = db.save_tender(tender)

    with db._connect() as conn:
        row = conn.execute(
            "SELECT start_date, end_date FROM tenders WHERE id = ?", (tender_id,)
        ).fetchone()
    assert row["start_date"] == start.isoformat()
    assert row["end_date"] == end.isoformat()

    tender.end_date = datetime(2026, 9, 21, 18, tzinfo=timezone.utc)
    tender.deadline = tender.end_date
    db.save_tender(tender)

    history = db.get_tender_history(tender_id)
    changed = [row for row in history if row["event_type"] == "updated"][-1]
    assert "end_date" in changed["changed_fields"]


def test_existing_legacy_schema_gets_date_columns(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE tenders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            external_id TEXT NOT NULL,
            unique_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            description TEXT DEFAULT '',
            price REAL,
            currency TEXT DEFAULT 'RUB',
            deadline TEXT,
            published_at TEXT,
            region TEXT DEFAULT '',
            customer TEXT DEFAULT '',
            law_type TEXT DEFAULT '',
            raw_data TEXT DEFAULT '{}',
            first_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    TenderDatabase(path)

    conn = sqlite3.connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tenders)")}
    conn.close()
    assert {"start_date", "end_date"} <= columns
