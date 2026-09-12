from datetime import timezone

from src.collectors.fabrikant_v3 import FabrikantV3Collector


def test_fabrikant_date_only_preserves_calendar_day_after_utc_normalization() -> None:
    parsed = FabrikantV3Collector._parse_human_date("12 сентября 2026")
    assert parsed is not None
    assert parsed.hour == 12
    assert parsed.minute == 0
    normalized = parsed.replace(tzinfo=timezone.utc)
    assert normalized.date().isoformat() == "2026-09-12"
