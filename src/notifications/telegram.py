"""Отправка уведомлений в Telegram."""

from __future__ import annotations

import html
import logging

import httpx

from src.models.tender import Tender, TenderAnalysis

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """Telegram-бот для уведомлений о тендерах."""

    PLATFORM_NAMES = {
        "eis": "ЕИС",
        "b2b_center": "B2B-Center",
        "fabrikant": "Фабрикант",
        "fabricant": "Фабрикант",
        "rts_tender": "РТС-тендер",
        "tmk": "ТМК",
        "rosatom": "Росатом",
    }

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        dry_run_when_no_token: bool = True,
        enabled: bool = True,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.dry_run_when_no_token = dry_run_when_no_token
        self.enabled = bool(enabled)

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_tender_alert(
        self,
        tender: Tender,
        analysis: TenderAnalysis,
        chat_id: str | None = None,
    ) -> bool:
        """Send an alert to an explicit chat or fall back to configured chat_id.

        Per-user Telegram searches must not silently deliver to the administrator's
        global ``TELEGRAM_CHAT_ID``.  ``chat_id`` is therefore an explicit override
        used by the multi-user bot, while CLI/scheduled runs keep the legacy default.
        """
        if not self.enabled:
            logger.info("Telegram: уведомления отключены настройкой notifications.telegram.enabled=false")
            return False
        message = self.format_message(tender, analysis)
        target_chat_id = str(chat_id).strip() if chat_id is not None else self.chat_id
        if not self.bot_token or not target_chat_id:
            if self.dry_run_when_no_token:
                logger.info(
                    "Telegram [DRY-RUN]: сообщение не отправлено (нет токена/chat_id)\n%s",
                    message,
                )
                return False
            raise RuntimeError("TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID не заданы в .env")
        return self._send(message, chat_id=target_chat_id)

    def send_text(self, text: str, chat_id: str | None = None) -> bool:
        if not self.enabled:
            logger.info("Telegram: уведомления отключены настройкой notifications.telegram.enabled=false")
            return False
        target_chat_id = str(chat_id).strip() if chat_id is not None else self.chat_id
        if not self.bot_token or not target_chat_id:
            logger.info("Telegram [DRY-RUN]: %s", text)
            return False
        return self._send(text, chat_id=target_chat_id)

    def _send(self, text: str, chat_id: str | None = None) -> bool:
        target_chat_id = str(chat_id).strip() if chat_id is not None else self.chat_id
        url = TELEGRAM_API.format(token=self.bot_token)
        payload = {
            "chat_id": target_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                try:
                    data = response.json()
                except ValueError as exc:
                    raise RuntimeError("Telegram API вернул некорректный JSON") from exc
                if not isinstance(data, dict) or data.get("ok") is not True:
                    description = data.get("description") if isinstance(data, dict) else None
                    error_code = data.get("error_code") if isinstance(data, dict) else None
                    suffix = f" ({error_code})" if error_code is not None else ""
                    raise RuntimeError(
                        f"Telegram API завершился ошибкой{suffix}: {description or 'unknown error'}"
                    )
            logger.info("Telegram: сообщение отправлено в chat_id=%s", target_chat_id)
            return True
        except (httpx.HTTPError, RuntimeError) as exc:
            logger.error("Telegram: ошибка отправки в chat_id=%s: %s", target_chat_id, exc)
            return False

    @classmethod
    def platform_name(cls, platform: str) -> str:
        value = str(platform or "").strip()
        return cls.PLATFORM_NAMES.get(value, value or "Не указана")

    @classmethod
    def format_message(cls, tender: Tender, analysis: TenderAnalysis) -> str:
        score = analysis.relevance_score
        emoji = "🔔" if score >= 70 else "📋"
        title = html.escape(str(tender.title or "Без названия"))
        customer = html.escape(str(tender.customer or "Заказчик не указан"))
        summary = html.escape(str(analysis.summary or ""))
        url = html.escape(str(tender.url or ""), quote=True)

        price_str = "не указан"
        if tender.price is not None:
            price_str = f"{tender.price:,.0f} {tender.currency}".replace(",", " ")
        deadline_str = tender.deadline.strftime("%d.%m.%Y") if tender.deadline else "не указан"

        risks = ""
        if analysis.risks:
            safe_risks = [html.escape(str(r)) for r in analysis.risks[:3]]
            risks = "\n⚠️ <b>Риски:</b> " + "; ".join(safe_risks)

        stub_note = "\n<i>(ИИ-заглушка — используется вместо локального Ollama)</i>" if analysis.is_stub else ""
        rec_map = {
            "participate": "✅ Участвовать",
            "skip": "❌ Пропустить",
            "review": "🔍 На проверку",
        }
        rec = html.escape(str(rec_map.get(analysis.recommendation, analysis.recommendation or "")))
        platform = html.escape(cls.platform_name(tender.platform))

        return (
            f"{emoji} <b>Новый тендер ({score}/100)</b>\n\n"
            f"🏷️ <b>Площадка:</b> {platform}\n"
            f"📋 {title}\n"
            f"💰 {price_str} | ⏰ до {deadline_str}\n"
            f"🏢 {customer}\n\n"
            f"📝 {summary}\n"
            f"{risks}\n"
            f"💡 <b>Рекомендация:</b> {rec}"
            f"{stub_note}\n\n"
            f"🔗 <a href=\"{url}\">Открыть тендер</a>"
        )
