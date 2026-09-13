from src.settings import AppSettings


def _settings(**config):
    return AppSettings(config=config, keywords={})


def test_string_false_is_not_truthy_for_scheduler_and_telegram():
    settings = _settings(
        scheduler={"run_on_start": "false"},
        notifications={"telegram": {"dry_run_when_no_token": "false"}},
    )

    assert settings.run_on_start is False
    assert settings.telegram_dry_run is False


def test_string_true_is_truthy_for_scheduler_and_ai_stub():
    settings = _settings(
        scheduler={"run_on_start": "yes"},
        ai={"use_stub_when_no_key": "on"},
    )

    assert settings.run_on_start is True
    assert settings.ai_use_stub is True


def test_unknown_boolean_values_use_safe_defaults():
    settings = _settings(
        scheduler={"run_on_start": "maybe"},
        notifications={"telegram": {"dry_run_when_no_token": "maybe"}},
        ai={"use_stub_when_no_key": "maybe"},
    )

    assert settings.run_on_start is True
    assert settings.telegram_dry_run is True
    assert settings.ai_use_stub is False

def test_telegram_enabled_flag_is_parsed_safely():
    assert _settings(notifications={"telegram": {"enabled": "false"}}).telegram_enabled is False
    assert _settings(notifications={"telegram": {"enabled": "yes"}}).telegram_enabled is True
    assert _settings(notifications={"telegram": {"enabled": "maybe"}}).telegram_enabled is True
