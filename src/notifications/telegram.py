"""Отправка уведомлений в Telegram."""

from __future__ import annotations

import logging

import httpx

from src.models.tender import Tender, TenderAnalysis

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """
    Telegram-бот для уведомлений о тендерах.

    Если токен не задан — работает в dry-run режиме (только лог).
    """

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        dry_run_when_no_token: bool = True,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.dry_run_when_no_token = dry_run_when_no_token

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_tender_alert(self, tender: Tender, analysis: TenderAnalysis) -> bool:
        message = self.format_message(tender, analysis)

        if not self.is_configured:
            if self.dry_run_when_no_token:
                logger.info(
                    "Telegram [DRY-RUN]: сообщение не отправлено (нет токена/chat_id)\n%s",
                    message,
                )
                return False
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID не заданы в .env"
            )

        return self._send(message)

    def send_text(self, text: str) -> bool:
        if not self.is_configured:
            logger.info("Telegram [DRY-RUN]: %s", text)
            return False
        return self._send(text)

    def _send(self, text: str) -> bool:
        url = TELEGRAM_API.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
            logger.info("Telegram: сообщение отправлено")
            return True
        except httpx.HTTPError as exc:
            logger.error("Telegram: ошибка отправки: %s", exc)
            return False

    @staticmethod
    def format_message(tender: Tender, analysis: TenderAnalysis) -> str:
        score = analysis.relevance_score
        emoji = "🔔" if score >= 70 else "📋"

        price_str = "не указан"
        if tender.price is not None:
            price_str = f"{tender.price:,.0f} {tender.currency}".replace(",", " ")

        deadline_str = "не указан"
        if tender.deadline:
            deadline_str = tender.deadline.strftime("%d.%m.%Y")

        risks = ""
        if analysis.risks:
            risks = "\n⚠️ <b>Риски:</b> " + "; ".join(analysis.risks[:3])

        stub_note = "\n<i>(ИИ-заглушка — подключите API-ключ)</i>" if analysis.is_stub else ""

        rec_map = {
            "participate": "✅ Участвовать",
            "skip": "❌ Пропустить",
            "review": "🔍 На проверку",
        }
        rec = rec_map.get(analysis.recommendation, analysis.recommendation)

        return (
            f"{emoji} <b>Новый тендер ({score}/100)</b>\n\n"
            f"📋 {tender.title}\n"
            f"💰 {price_str} | ⏰ до {deadline_str}\n"
            f"🏢 {tender.customer or 'Заказчик не указан'}\n\n"
            f"📝 {analysis.summary}\n"
            f"{risks}\n"
            f"💡 <b>Рекомендация:</b> {rec}"
            f"{stub_note}\n\n"
            f"🔗 <a href=\"{tender.url}\">Открыть тендер</a>"
        )
