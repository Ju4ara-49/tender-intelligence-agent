from datetime import datetime, timezone

from src.analytics.market import MarketAnalytics
from src.models.tender import Tender, TenderAnalysis
from src.storage.database import TenderDatabase


def test_market_snapshot_aggregates_tenders(tmp_path):
    db = TenderDatabase(tmp_path / "tenders.db")
    first = Tender(
        platform="eis",
        external_id="1",
        title="Подшипник",
        url="https://example.test/1",
        price=100000,
        region="Москва",
        customer="Заказчик А",
        law_type="44 ФЗ",
        published_at=datetime.now(timezone.utc),
    )
    second = Tender(
        platform="b2b_center",
        external_id="2",
        title="Муфта",
        url="https://example.test/2",
        price=300000,
        region="Москва",
        customer="Заказчик Б",
        law_type="223 ФЗ",
        published_at=datetime.now(timezone.utc),
    )
    first_id = db.save_tender(first)
    second_id = db.save_tender(second)
    db.save_analysis(first_id, TenderAnalysis(90, "ok", "participate"))
    db.save_analysis(second_id, TenderAnalysis(60, "ok", "review"))

    snapshot = MarketAnalytics(db).snapshot(days=30)

    assert snapshot.total_tenders == 2
    assert snapshot.total_value == 400000
    assert snapshot.average_price == 200000
    assert snapshot.average_ai_score == 75
    assert snapshot.high_score_count == 1
    assert snapshot.by_region[0]["name"] == "Москва"
    assert snapshot.by_customer[0]["tenders"] == 1
    assert {row["name"] for row in snapshot.by_law} == {"44 ФЗ", "223 ФЗ"}
