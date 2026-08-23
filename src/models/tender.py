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

    start_date: datetime | None = None
    end_date: datetime | None = None
    published_at: datetime | None = None
    deadline: datetime | None = None

    region: str = ""
    customer: str = ""
    law_type: str = ""

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

    @classmethod
    def _text_from_value(cls, value: Any) -> list[str]:
        """Рекурсивно извлечь текст из лотов/specification/raw_data."""
        if value is None:
            return []
        if isinstance(value, str):
            value = value.strip()
            return [value] if value else []
        if isinstance(value, dict):
            result: list[str] = []
            for key, item in value.items():
                # Ключи обычно являются техническими именами и создают шум,
                # поэтому индексируем их только как текст, если они содержат
                # пользовательские пробелы/русские слова.
                if isinstance(key, str) and (" " in key or any("а" <= ch.lower() <= "я" for ch in key)):
                    result.extend(cls._text_from_value(key))
                result.extend(cls._text_from_value(item))
            return result
        if isinstance(value, (list, tuple, set)):
            result: list[str] = []
            for item in value:
                result.extend(cls._text_from_value(item))
            return result
        return [str(value)]

    @property
    def full_text(self) -> str:
        """Полный поисковый текст, включая детали, лоты и спецификации."""
        parts = [self.title, self.description, self.customer, self.region]
        raw = self.raw_data or {}
        for key in ("details", "lots", "lot", "specification", "specifications", "items", "products"):
            if key in raw:
                parts.extend(self._text_from_value(raw.get(key)))

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
        self.relevance_score = max(0, min(100, int(self.relevance_score)))
        allowed_recommendations = {"participate", "review", "skip"}
        if self.recommendation not in allowed_recommendations:
            self.recommendation = "review"
        if not isinstance(self.risks, list):
            self.risks = [str(self.risks)]
        self.risks = [str(risk).strip() for risk in self.risks if str(risk).strip()][:3]

    @property
    def is_relevant(self) -> bool:
        return self.relevance_score >= 50
