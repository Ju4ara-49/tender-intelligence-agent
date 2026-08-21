"""Модели тендера и результата AI-анализа."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Tender:
    """Единая модель тендера для всех платформ."""

    platform: str
    external_id: str
    title: str
    url: str

    description: str = ""
    price: float | None = None
    currency: str = "RUB"

    # Даты проведения процедуры.
    start_date: datetime | None = None
    end_date: datetime | None = None
    published_at: datetime | None = None

    # Крайний срок подачи заявок.
    # Это основное поле, которое используется оркестратором,
    # базой данных, AI-анализом и Telegram-уведомлением.
    deadline: datetime | None = None

    region: str = ""
    customer: str = ""
    law_type: str = ""

    # Коммерческие условия закупки.
    advance_required: bool = False
    advance_percent: float | None = None
    postpayment_days: int | None = None
    application_security_percent: float | None = None
    contract_security_percent: float | None = None

    raw_data: dict[str, Any] = field(default_factory=dict)

    @property
    def unique_key(self) -> str:
        """Уникальный ключ тендера для защиты от дублей."""
        return f"{self.platform}:{self.external_id}"

    @property
    def full_text(self) -> str:
        """
        Объединённый текст тендера для поиска, фильтрации и AI-анализа.
        """
        parts = [
            self.title,
            self.description,
            self.customer,
            self.region,
        ]

        return " ".join(
            str(part).strip()
            for part in parts
            if part is not None and str(part).strip()
        ).strip()


@dataclass
class TenderAnalysis:
    """Результат AI-анализа тендера."""

    relevance_score: int
    summary: str
    recommendation: str

    risks: list[str] = field(default_factory=list)

    budget_note: str = ""
    deadline_note: str = ""

    is_stub: bool = False

    def __post_init__(self) -> None:
        """Нормализация и проверка результата анализа."""

        self.relevance_score = max(
            0,
            min(100, int(self.relevance_score)),
        )

        allowed_recommendations = {
            "participate",
            "review",
            "skip",
        }

        if self.recommendation not in allowed_recommendations:
            self.recommendation = "review"

        if not isinstance(self.risks, list):
            self.risks = [str(self.risks)]

        self.risks = [
            str(risk).strip()
            for risk in self.risks
            if str(risk).strip()
        ][:3]

    @property
    def is_relevant(self) -> bool:
        """Тендер считается потенциально релевантным от 50 баллов."""
        return self.relevance_score >= 50

