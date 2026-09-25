from unittest.mock import MagicMock
from src.collectors.browser_public_reliable import ReliableRtsTenderCollector

def test_reliable_rts_uses_public_fallback_on_antiddos_503(monkeypatch):
    collector = ReliableRtsTenderCollector({})
    monkeypatch.setattr(collector, "timeout_ms", 5000)
    monkeypatch.setattr(collector, "_tenderguru_fallback", lambda query, reason: ["fallback-result"])
    response = MagicMock(); response.status = 503
    page = MagicMock(); page.locator.return_value.count.return_value = 1; page.locator.return_value.inner_text.return_value = "Anti-DDoS block"
    fake_browser = MagicMock(); fake_context = MagicMock(); fake_context.new_page.return_value = page; fake_browser.new_context.return_value = fake_context
    fake_pw = MagicMock(); fake_pw.__enter__.return_value = fake_pw; fake_pw.chromium.launch.return_value = fake_browser
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: fake_pw)
    monkeypatch.setattr(collector, "_goto", lambda *args, **kwargs: response)
    assert collector._search_one("podshipniki") == ["fallback-result"]
    fake_browser.close.assert_called_once()
