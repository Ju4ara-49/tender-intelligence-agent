from unittest.mock import MagicMock, patch

import pytest

from src.telegram_bot import TelegramBot


def _bot():
    settings = MagicMock()
    settings.telegram_bot_token = "token"
    settings.telegram_chat_id = "1"
    orchestrator = MagicMock()
    return TelegramBot(settings, orchestrator)


def test_call_accepts_successful_telegram_response():
    bot = _bot()
    response = MagicMock()
    response.json.return_value = {"ok": True, "result": []}
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.post.return_value = response
    with patch("src.telegram_bot.httpx.Client", return_value=client):
        assert bot._call("getUpdates") == {"ok": True, "result": []}


@pytest.mark.parametrize("payload", [
    {"ok": False, "error_code": 400, "description": "Bad Request"},
    {"ok": False, "error_code": 403, "description": "Forbidden"},
])
def test_call_rejects_api_level_error_even_with_http_200(payload):
    bot = _bot()
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.post.return_value = response
    with patch("src.telegram_bot.httpx.Client", return_value=client):
        with pytest.raises(RuntimeError, match="Telegram API sendMessage завершился ошибкой"):
            bot._call("sendMessage", chat_id="1", text="test")


def test_send_returns_false_for_api_level_error():
    bot = _bot()
    with patch.object(bot, "_call", side_effect=RuntimeError("Telegram API sendMessage завершился ошибкой (400)")):
        assert bot._send("1", "test") is None
