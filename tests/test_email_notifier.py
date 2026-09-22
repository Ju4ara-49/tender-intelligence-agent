"""Unit-тесты EmailNotifier: payload, вложение и обработка ошибок.

До этого аудита Email-интеграция не имела ни одного теста.
SMTP не вызывается по-настоящему — smtplib.SMTP_SSL патчится.
"""
from pathlib import Path
from unittest.mock import patch

from src.notifications.email import EmailNotifier


def _notifier(**overrides) -> EmailNotifier:
    params = dict(
        enabled=True,
        smtp_host="smtp.test",
        smtp_port=465,
        username="from@test",
        password="secret",
        recipient="to@test",
    )
    params.update(overrides)
    return EmailNotifier(**params)


def _excel_file(tmp_path: Path, name: str = "search_001_x.xlsx") -> Path:
    path = tmp_path / name
    path.write_bytes(b"fake-xlsx-bytes")
    return path


def test_disabled_notifier_returns_false_without_smtp(tmp_path):
    notifier = _notifier(enabled=False)
    with patch("smtplib.SMTP_SSL") as smtp_cls:
        assert notifier.send_excel(_excel_file(tmp_path), 1) is False
    smtp_cls.assert_not_called()


def test_missing_excel_file_returns_false(tmp_path):
    assert _notifier().send_excel(tmp_path / "missing.xlsx", 1) is False


def test_missing_credentials_returns_false_without_smtp(tmp_path):
    for override in ({"username": ""}, {"password": ""}, {"recipient": ""}):
        with patch("smtplib.SMTP_SSL") as smtp_cls:
            assert _notifier(**override).send_excel(_excel_file(tmp_path), 1) is False
        smtp_cls.assert_not_called()


def test_successful_send_builds_message_with_excel_attachment(tmp_path):
    excel_path = _excel_file(tmp_path, "search_007_2026.xlsx")
    with patch("smtplib.SMTP_SSL") as smtp_cls:
        smtp = smtp_cls.return_value.__enter__.return_value
        assert _notifier().send_excel(excel_path, 7) is True

    smtp_cls.assert_called_once_with("smtp.test", 465, timeout=30)
    smtp.login.assert_called_once_with("from@test", "secret")
    message = smtp.send_message.call_args[0][0]

    assert message["Subject"] == "Результаты поиска тендеров №007"
    assert message["From"] == "from@test"
    assert message["To"] == "to@test"
    text_part = next(part for part in message.iter_parts() if part.get_content_type() == "text/plain")
    assert "Excel-файл прикреплён" in text_part.get_content()

    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    attachment = attachments[0]
    assert attachment.get_filename() == "search_007_2026.xlsx"
    assert attachment.get_content_maintype() == "application"
    assert attachment.get_content_subtype() == "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert attachment.get_payload(decode=True) == b"fake-xlsx-bytes"


def test_smtp_failure_returns_false_and_does_not_raise(tmp_path):
    with patch("smtplib.SMTP_SSL", side_effect=OSError("connection refused")):
        assert _notifier().send_excel(_excel_file(tmp_path), 3) is False


def test_zero_padded_search_number_in_subject(tmp_path):
    with patch("smtplib.SMTP_SSL") as smtp_cls:
        smtp = smtp_cls.return_value.__enter__.return_value
        _notifier().send_excel(_excel_file(tmp_path), 42)
    message = smtp.send_message.call_args[0][0]
    assert message["Subject"] == "Результаты поиска тендеров №042"