from datetime import datetime, timezone

from src.models.tender import Tender


def test_naive_tender_dates_are_treated_as_moscow_and_stored_as_utc():
    tender = Tender(
        platform="rts_tender",
        external_id="1",
        title="Тест",
        url="https://example.test/1",
        deadline=datetime(2026, 9, 20, 18, 0),
    )
    assert tender.deadline.tzinfo == timezone.utc
    assert tender.deadline.hour == 15


def test_aware_tender_dates_are_converted_to_utc_without_changing_instant():
    tender = Tender(
        platform="rts_tender",
        external_id="2",
        title="Тест",
        url="https://example.test/2",
        deadline=datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc),
    )
    assert tender.deadline == datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
