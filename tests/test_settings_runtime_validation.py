import pytest

from src.settings import AppSettings


def _settings(interval):
    return AppSettings(config={"scheduler": {"interval_minutes": interval}}, keywords={})


def test_scheduler_interval_accepts_positive_integer():
    assert _settings(15).scheduler_interval_minutes == 15


@pytest.mark.parametrize("value", [0, -1, True, False, "", "abc", None])
def test_scheduler_interval_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        _settings(value).scheduler_interval_minutes
