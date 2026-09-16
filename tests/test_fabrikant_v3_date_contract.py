from datetime import timezone
from unittest.mock import patch

from src.collectors.fabrikant_v3 import FabrikantV3Collector
from src.models.tender import Tender


def test_fabrikant_date_only_preserves_calendar_day_after_utc_normalization() -> None:
    parsed = FabrikantV3Collector._parse_human_date("12 сентября 2026")
    assert parsed is not None
    assert parsed.hour == 12
    assert parsed.minute == 0
    normalized = parsed.replace(tzinfo=timezone.utc)
    assert normalized.date().isoformat() == "2026-09-12"


def test_get_details_normalizes_recovered_publication_date_to_utc() -> None:
    bare = Tender(
        platform="fabrikant",
        external_id="1",
        title="Поставка станка",
        url="https://fabrikant.ru/procedure/1",
        description="Дата публикации: 12 сентября 2026",
    )
    with patch(
        "src.collectors.fabrikant_v2.FabrikantV2Collector.get_details",
        return_value=bare,
    ):
        detailed = FabrikantV3Collector().get_details("1")
    assert detailed is not None
    assert detailed.published_at is not None
    assert detailed.published_at.tzinfo is not None
    assert detailed.start_date is not None
    assert detailed.start_date.tzinfo is not None
