from src.collectors.registry import ALL_COLLECTORS, get_enabled_collectors


def test_registry_contains_exact_supported_platforms():
    platforms = [collector.platform for collector in (cls() for cls in ALL_COLLECTORS)]
    assert platforms == ["eis", "b2b_center", "fabrikant", "rts_tender", "tmk", "rosatom"]
    assert "unipro" not in platforms


def test_explicit_platform_selection_is_intersection_with_config():
    config = {
        "collectors": {
            "fabrikant": {"enabled": True},
            "rosatom": {"enabled": False},
        }
    }
    selected = get_enabled_collectors(config, enabled_platforms=["fabrikant", "rosatom"])
    assert [collector.platform for collector in selected] == ["fabrikant"]


def test_explicit_selection_cannot_bypass_disabled_platform():
    config = {"collectors": {"fabrikant": {"enabled": False}}}
    selected = get_enabled_collectors(config, enabled_platforms=["fabrikant"])
    assert selected == []
