"""Компактная карточка решения по тендеру для Telegram и Excel.

Модуль не придумывает отсутствующие данные: неизвестные поля помечаются как
«не указано», а AI-вывод используется только если он уже был рассчитан.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from src.models.tender import Tender, TenderAnalysis
from src.workflow import STATUS_NAMES, WorkflowState


def _money(value: float | None) -> str:
    if value is None:
        return "не указана"
    return f"{value:,.2f}".replace(",", " ").replace(".00", "") + " ₽"


def _deadline(value: datetime | None) -> str:
    if value is None:
        return "не указан"
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    days = (current - datetime.now(timezone.utc)).total_seconds() / 86400
    return f"{current.astimezone().strftime('%d.%m.%Y %H:%M')} (осталось {max(0, days):.1f} дн.)"


def _percent(value: float | None) -> str:
    return "не указано" if value is None else f"{value:g}%"


def render_decision_card(tender: Tender, analysis: TenderAnalysis | None = None, workflow: WorkflowState | None = None) -> str:
    """Вернуть HTML-карточку, безопасную для Telegram parse_mode=HTML."""
    lines = [
        f"<b>{escape(tender.title or 'Без названия')}</b>",
        f"Площадка: <b>{escape(tender.platform)}</b>",
        f"Цена: <b>{_money(tender.price)}</b>",
        f"Срок подачи: <b>{_deadline(tender.deadline)}</b>",
        f"Аванс: <b>{'да' if tender.advance_required else 'нет/не указан'}</b>" + (f" ({_percent(tender.advance_percent)})" if tender.advance_percent is not None else ""),
        f"Постоплата: <b>{tender.postpayment_days} дн.</b>" if tender.postpayment_days is not None else "Постоплата: <b>не указана</b>",
        f"Обеспечение заявки: <b>{_percent(tender.application_security_percent)}</b>",
        f"Обеспечение контракта: <b>{_percent(tender.contract_security_percent)}</b>",
        f"Заказчик: <b>{escape(tender.customer or 'не указан')}</b>",
        f"Регион: <b>{escape(tender.region or 'не указан')}</b>",
        f"Закон: <b>{escape(tender.law_type or 'не указан')}</b>",
    ]
    if analysis is not None:
        lines.extend([
            f"AI-релевантность: <b>{analysis.relevance_score}/100</b>",
            f"Рекомендация: <b>{escape(analysis.recommendation)}</b>",
            f"Кратко: {escape(analysis.summary or 'не указано')}",
        ])
        if analysis.risks:
            lines.append("Риски: " + "; ".join(escape(risk) for risk in analysis.risks))
    if workflow is not None:
        lines.append(f"Статус: <b>{escape(STATUS_NAMES.get(workflow.status, workflow.status))}</b>")
        if workflow.tags:
            lines.append("Метки: " + ", ".join(escape(tag) for tag in workflow.tags))
        if workflow.comment:
            lines.append(f"Комментарий: {escape(workflow.comment)}")
    lines.append(f"<a href=\"{escape(tender.url, quote=True)}\">Открыть тендер</a>")
    return "\n".join(lines)
