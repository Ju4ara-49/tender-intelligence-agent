"""Отправка уведомлений в Telegram."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

import httpx

from src.models.tender import Tender, TenderAnalysis
from src.security_redaction import redact_secrets
from src.tenderplan import TenderTaskStore

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
        task_store: TenderTaskStore | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.dry_run_when_no_token = dry_run_when_no_token
        self.task_store = task_store

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_tender_alert(self, tender: Tender, analysis: TenderAnalysis, chat_id: str | None = None, tender_id: int | None = None) -> bool:
        message = self.format_message(tender, analysis)
        target_chat_id = str(chat_id).strip() if chat_id is not None else self.chat_id
        reply_markup = self._tender_keyboard(tender, tender_id)
        if not self.bot_token or not target_chat_id:
            if self.dry_run_when_no_token:
                logger.info("Telegram [DRY-RUN]: сообщение не отправлено (нет токена/chat_id)\n%s", message)
                return False
            raise RuntimeError("TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID не заданы в .env")
        return self._send(message, chat_id=target_chat_id, reply_markup=reply_markup)

    @staticmethod
    def _tender_keyboard(tender: Tender, tender_id: int | None) -> dict:
        rows: list[list[dict[str, str]]] = []
        resolved_tender_id = tender_id
        if resolved_tender_id is None:
            raw = tender.raw_data if isinstance(tender.raw_data, dict) else {}
            raw_id = raw.get("db_id")
            if isinstance(raw_id, int) and raw_id > 0:
                resolved_tender_id = raw_id
            elif isinstance(raw_id, str) and raw_id.isdigit() and int(raw_id) > 0:
                resolved_tender_id = int(raw_id)
        if resolved_tender_id is not None and int(resolved_tender_id) > 0:
            callback_data = f"crm:status:{int(resolved_tender_id)}:participating"
        else:
            callback_data = f"crm:participate:{tender.platform}:{tender.external_id}"
        if len(callback_data.encode("utf-8")) <= 64:
            rows.append([{"text": "УЧАСТВОВАТЬ", "callback_data": callback_data}])
        else:
            logger.warning("Telegram: CRM callback too long for %s:%s; participation button omitted", tender.platform, tender.external_id)
        if tender.url:
            rows.append([{"text": "Открыть тендер", "url": str(tender.url)}])
        return {"inline_keyboard": rows}

    def send_text(self, text: str, chat_id: str | None = None) -> bool:
        """Send plain text or apply the configured no-credentials dry-run policy."""
        target_chat_id = str(chat_id).strip() if chat_id is not None else self.chat_id
        if not self.bot_token or not target_chat_id:
            if self.dry_run_when_no_token:
                logger.info("Telegram [DRY-RUN]: %s", text)
                return False
            raise RuntimeError("TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID не заданы в .env")
        return self._send(text, chat_id=target_chat_id)

    def _send(self, text: str, chat_id: str | None = None, reply_markup: dict | None = None) -> bool:
        target_chat_id = str(chat_id).strip() if chat_id is not None else self.chat_id
        url = TELEGRAM_API.format(token=self.bot_token)
        payload = {"chat_id": target_chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                body = response.json()
            if not isinstance(body, dict) or body.get("ok") is not True:
                description = body.get("description") if isinstance(body, dict) else "invalid Telegram response"
                logger.error("Telegram: API отклонил сообщение chat_id=%s: %s", target_chat_id, description)
                return False
            logger.info("Telegram: сообщение отправлено в chat_id=%s", target_chat_id)
            return True
        except (httpx.HTTPError, ValueError) as exc:
            safe_exc = redact_secrets(str(exc), (self.bot_token,) if self.bot_token else None)
            logger.error("Telegram: ошибка отправки в chat_id=%s: %s", target_chat_id, safe_exc)
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
        start_str = tender.start_date.strftime("%d.%m.%Y") if tender.start_date else "не указана"
        end_str = tender.end_date.strftime("%d.%m.%Y") if tender.end_date else "не указана"
        deadline_str = tender.deadline.strftime("%d.%m.%Y") if tender.deadline else "не указан"
        risks = ""
        if analysis.risks:
            safe_risks = [html.escape(str(r)) for r in analysis.risks[:3]]
            risks = "\n⚠️ <b>Риски AI:</b> " + "; ".join(safe_risks)
        risk_assessment = tender.raw_data.get("risk_assessment") if isinstance(tender.raw_data, dict) else {}
        if isinstance(risk_assessment, dict) and risk_assessment.get("level"):
            level = html.escape(str(risk_assessment["level"]))
            factor_codes = [
                html.escape(str(item.get("code")))
                for item in risk_assessment.get("factors", [])
                if isinstance(item, dict) and item.get("code")
            ]
            deterministic = f"\n🛡️ <b>Risk Engine:</b> {level}"
            if factor_codes:
                deterministic += " — " + ", ".join(factor_codes[:4])
            risks += deterministic
        stub_note = "\n<i>(ИИ-заглушка — используется вместо локального Ollama)</i>" if analysis.is_stub else ""
        rec_map = {"participate": "Участвовать", "skip": "Пропустить", "review": "На проверку"}
        rec = html.escape(str(rec_map.get(analysis.recommendation, analysis.recommendation or "")))
        platform = html.escape(cls.platform_name(tender.platform))
        return (
            f"{emoji} <b>Новый тендер ({score}/100)</b>\n\n"
            f"🏷️ <b>Площадка:</b> {platform}\n"
            f"📋 {title}\n"
            f"💰 {price_str}\n"
            f"📅 <b>Дата начала:</b> {start_str}\n"
            f"📅 <b>Дата окончания:</b> {end_str}\n"
            f"⏰ <b>Срок подачи:</b> {deadline_str}\n"
            f"🏢 {customer}\n\n"
            f"📝 {summary}\n{risks}\n"
            f"💡 <b>Рекомендация:</b> {rec}{stub_note}\n\n"
            f"🔗 <a href=\"{url}\">Открыть тендер</a>"
        )
