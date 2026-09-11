from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from src.models.tender import Tender
from src.storage.database import TenderDatabase


def _tender(price: float = 100.0, title: str = "Подшипник") -> Tender:
    return Tender(
        platform="eis",
        external_id="123",
        title=title,
        url="https://example.test/tender/123",
        description="Тестовый тендер",
        price=price,
        deadline=datetime.now(timezone.utc) + timedelta(days=20),
        region="Москва",
        customer="Тестовый заказчик",
        raw_data={"details": {"price": price}},
    )


def test_search_numbers_are_unique_under_concurrency(tmp_path):
    db = TenderDatabase(tmp_path / "test.sqlite3")
    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(lambda _: db.next_search_number(), range(40)))
    assert sorted(numbers) == list(range(1, 41))


def test_tender_history_records_creation_and_real_change(tmp_path):
    db = TenderDatabase(tmp_path / "test.sqlite3")
    tender_id = db.save_tender(_tender(price=100.0))
    history = db.get_tender_history(tender_id)
    assert len(history) == 1
    assert history[0]["event_type"] == "created"

    db.save_tender(_tender(price=100.0))
    assert len(db.get_tender_history(tender_id)) == 1

    db.save_tender(_tender(price=125.0, title="Изменённый подшипник"))
    history = db.get_tender_history(tender_id)
    assert len(history) == 2
    assert history[-1]["event_type"] == "updated"
    assert "price" in history[-1]["changed_fields"]
    assert "title" in history[-1]["changed_fields"]


def test_sqlite_wal_and_busy_timeout_are_enabled(tmp_path):
    db = TenderDatabase(tmp_path / "test.sqlite3")
    with db._connect() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert str(journal_mode).lower() == "wal"
    assert busy_timeout >= 10000
