"""Отправка результатов поиска по электронной почте."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Отправляет готовый Excel-файл как вложение через SMTP."""

    def __init__(
        self,
        *,
        enabled: bool,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        recipient: str,
    ) -> None:
        self.enabled = enabled
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.recipient = recipient

    def send_excel(self, excel_path: Path | str, search_number: int) -> bool:
        """Отправить только Excel текущего поиска во вложении."""
        if not self.enabled:
            logger.info("Email: отправка отключена.")
            return False

        path = Path(excel_path)
        if not path.is_file():
            logger.error("Email: Excel-файл не найден: %s", path)
            return False

        if not self.username or not self.password or not self.recipient:
            logger.error(
                "Email: не настроены EMAIL_FROM/EMAIL_PASSWORD/EMAIL_TO."
            )
            return False

        message = EmailMessage()
        message["Subject"] = f"Результаты поиска тендеров №{search_number:03d}"
        message["From"] = self.username
        message["To"] = self.recipient
        message.set_content(
            f"Результаты поиска тендеров №{search_number:03d}.\n"
            "Excel-файл прикреплён к письму."
        )

        with path.open("rb") as file:
            data = file.read()

        message.add_attachment(
            data,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=path.name,
        )

        try:
            with smtplib.SMTP_SSL(
                self.smtp_host,
                self.smtp_port,
                timeout=30,
            ) as smtp:
                smtp.login(self.username, self.password)
                smtp.send_message(message)

            logger.info(
                "Email: Excel поиска №%03d отправлен на %s",
                search_number,
                self.recipient,
            )
            return True

        except Exception:
            logger.exception(
                "Email: ошибка отправки Excel поиска №%03d",
                search_number,
            )
            return False
