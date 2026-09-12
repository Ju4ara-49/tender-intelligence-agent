from __future__ import annotations

from datetime import datetime

from src.models.tender import Tender
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState


def test_tender_to_utc_is_idempotent() -> None:
    tender = Tender(
        platform="test",
        external_id="1",
        title="Test",
        url="https://example.test/1",
        deadline=datetime(2026, 9, 12, 12, 0),
    )
    first = tender.deadline
    tender.to_utc()
    assert tender.deadline == first
    assert tender.deadline.tzinfo is not None


def test_tender_detail_contract_defaults() -> None:
    tender = Tender(platform="test", external_id="1", title="Test", url="https://example.test/1")
    assert tender.customer_inn == ""
    assert tender.detail_status == "success"
    assert tender.detail_diagnostics == ""
    assert tender.documents == []


def test_notification_state_is_recipient_aware(tmp_path) -> None:
    db = TenderDatabase(tmp_path / "test.db")
    tender = Tender(platform="test", external_id="1", title="Test", url="https://example.test/1")
    tender_id = db.save_tender(tender)
    state = NotificationDeliveryState(db)

    state.mark_notified(tender, recipient_key="user-a")
    assert state.was_notified(tender, recipient_key="user-a")
    assert not state.was_notified(tender, recipient_key="user-b")

    with db._connect() as conn:
        rows = conn.execute(
            "SELECT recipient_key FROM notification_events WHERE tender_id = ?",
            (tender_id,),
        ).fetchall()
    assert {row["recipient_key"] for row in rows} == {"user-a"}


def test_detail_metadata_survives_raw_data_round_trip() -> None:
    tender = Tender(
        platform="test",
        external_id="docs-1",
        title="Test",
        url="https://example.test/docs-1",
        documents=[{"name": "Извещение", "url": "https://example.test/doc.pdf"}],
        field_sources={"customer": "detail.customer"},
    )
    restored = Tender(
        platform=tender.platform,
        external_id=tender.external_id,
        title=tender.title,
        url=tender.url,
        raw_data=tender.raw_data,
    )
    assert restored.documents == tender.documents
    assert restored.field_sources == tender.field_sources


def test_detail_contract_extracts_spaced_inn() -> None:
    from src.collectors.detail_contract import enforce_detail_contract

    tender = Tender(
        platform="dummy",
        external_id="2",
        title="Title",
        url="https://example.test/2",
        customer="ООО Тест",
        description="ИНН: 77 01 234567",
        price=100,
        deadline=datetime(2026, 9, 20, 12, 0),
    )

    class Collector:
        platform = "dummy"

        def get_details(self, external_id):
            return tender

    collector = Collector()
    enforce_detail_contract(collector)
    result = collector.get_details("2")
    assert result.customer_inn == "7701234567"
