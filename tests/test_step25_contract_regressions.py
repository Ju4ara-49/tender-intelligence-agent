from __future__ import annotations

from datetime import datetime

from src.filters.keyword_filter import KeywordFilter
from src.models.tender import Tender
from src.storage.database import TenderDatabase
from src.storage.notification_delivery import NotificationDeliveryState


def test_keyword_filter_does_not_match_short_stem_inside_unrelated_word() -> None:
    tender = Tender(platform="test", external_id="1", title="Станция", url="https://example.test/1")
    assert not KeywordFilter(include=["стан"], exclude=[]).matches(tender)


def test_keyword_filter_matches_russian_declensions() -> None:
    for title in ("Подшипник", "Подшипники", "Подшипников"):
        tender = Tender(platform="test", external_id=title, title=title, url="https://example.test")
        assert KeywordFilter(include=["подшипник"], exclude=[]).matches(tender)


def test_notification_delivery_state_has_database_and_stable_fingerprint(tmp_path) -> None:
    db = TenderDatabase(tmp_path / "test.db")
    state = NotificationDeliveryState(db)
    tender = Tender(
        platform="test",
        external_id="1",
        title="Подшипники",
        url="https://example.test/1",
        price=100.0,
        deadline=datetime(2030, 1, 1),
    )
    db.save_tender(tender)
    assert state.was_notified(tender) is False
    state.mark_notified(tender, payload={"test": True})
    assert state.was_notified(tender) is True


def test_tender_persists_normalized_commercial_values() -> None:
    tender = Tender(
        platform="test",
        external_id="1",
        title="Поставка",
        url="https://example.test/1",
        description="Предоплата 30%. Отсрочка платежа 20 календарных дней.",
    )
    normalized = tender.raw_data["_normalized"]
    assert normalized["advance_percent"] == 30.0
    assert normalized["advance_required"] is True
    assert normalized["postpayment_days"] == 20
