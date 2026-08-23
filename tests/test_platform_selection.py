import unittest

from src.collectors.registry import get_enabled_collectors
from src.telegram_settings import SUPPORTED_PLATFORMS


class PlatformSelectionTests(unittest.TestCase):
    def test_all_telegram_platforms_create_collectors(self):
        config = {
            "collectors": {
                platform: {"enabled": True}
                for platform in SUPPORTED_PLATFORMS
            }
        }
        collectors = get_enabled_collectors(config, enabled_platforms=list(SUPPORTED_PLATFORMS))
        self.assertEqual(
            {collector.platform for collector in collectors},
            set(SUPPORTED_PLATFORMS),
        )

    def test_explicit_selection_overrides_config(self):
        config = {
            "collectors": {
                platform: {"enabled": False}
                for platform in SUPPORTED_PLATFORMS
            }
        }
        collectors = get_enabled_collectors(config, enabled_platforms=["eis", "b2b_center"])
        self.assertEqual(
            {collector.platform for collector in collectors},
            {"eis", "b2b_center"},
        )


if __name__ == "__main__":
    unittest.main()
