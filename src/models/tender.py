"""Модели тендера и результата AI-анализа."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import re
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
    customer_inn: str = ""
    law_type: str = ""

    advance_required: bool = False
    advance_percent: float | None = None
    postpayment_days: int | None = None
    application_security_percent: float | None = None
    contract_security_percent: float | None = None

    detail_status: str = "success"
    detail_diagnostics: str = ""
    field_sources: dict[str, str] = field(default_factory=dict)
    documents: list[dict[str, str]] = field(default_factory=list)

    raw_data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize timestamps and recover common commercial terms from detail text."""
        self.to_utc()
        self._restore_detail_metadata()
        self._enrich_commercial_terms()
        self._persist_normalized_fields()

    def to_utc(self) -> Tender:
        """Normalize all tender timestamps to UTC."""
        moscow = timezone(timedelta(hours=3), name="MSK")
        for field_name in ("start_date", "end_date", "published_at", "deadline"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if value.tzinfo is None:
                value = value.replace(tzinfo=moscow)
            setattr(self, field_name, value.astimezone(timezone.utc))
        self._persist_normalized_fields()
        return self

    def _restore_detail_metadata(self) -> None:
        """Restore persisted detail documents/provenance from raw_data."""
        raw = self.raw_data if isinstance(self.raw_data, dict) else {}
        if not self.documents:
            documents = raw.get("documents")
            if isinstance(documents, list):
                restored = []
                for item in documents:
                    if not isinstance(item, dict):
                        continue
                    normalized = {
                        str(key): str(value).strip()
                        for key, value in item.items()
                        if value is not None and str(value).strip()
                    }
                    if normalized:
                        restored.append(normalized)
                self.documents = restored
        if not self.field_sources:
            sources = raw.get("field_sources")
            if isinstance(sources, dict):
                self.field_sources = {
                    str(key): str(value).strip()
                    for key, value in sources.items()
                    if value is not None and str(value).strip()
                }

    def _enrich_commercial_terms(self) -> None:
        """Fill unified commercial fields from Russian tender detail text."""
        raw = self.raw_data if isinstance(self.raw_data, dict) else {}
        text_parts: list[str] = []
        for value in (self.description, raw.get("details", ""), raw.get("document_text", ""), raw.get("document_contents", ""), raw.get("attachments_text", "")):
            text_parts.extend(self._text_from_value(value))
        text = re.sub(r"\s+", " ", " ".join(text_parts)).strip()
        if not text:
            return

        if self.advance_percent is None:
            self.advance_percent = self._extract_percent(text, ("аванс", "предоплата", "авансовый платеж", "авансовый платёж", "размер аванса"))
        if self.advance_percent is not None:
            self.advance_required = self.advance_percent > 0
        if self.postpayment_days is None:
            self.postpayment_days = self._extract_days(text, ("отсрочка платежа", "срок оплаты", "постоплата", "отсрочка оплаты"))
        if self.application_security_percent is None:
            self.application_security_percent = self._extract_percent(text, ("обеспечение заявки", "обеспечение предложения"))
        if self.contract_security_percent is None:
            self.contract_security_percent = self._extract_percent(text, ("обеспечение исполнения", "обеспечение контракта", "обеспечение договора"))

    def _persist_normalized_fields(self) -> None:
        """Keep normalized commercial fields in raw_data for SQLite round-trips."""
        if not isinstance(self.raw_data, dict):
            self.raw_data = {}
        if self.documents:
            self.raw_data["documents"] = [dict(item) for item in self.documents]
        if self.field_sources:
            self.raw_data["field_sources"] = dict(self.field_sources)
        self.raw_data["_normalized"] = {
            "advance_required": bool(self.advance_required),
            "advance_percent": self.advance_percent,
            "postpayment_days": self.postpayment_days,
            "application_security_percent": self.application_security_percent,
            "contract_security_percent": self.contract_security_percent,
            "customer_inn": self.customer_inn,
        }

    @staticmethod
    def _extract_percent(text: str, labels: tuple[str, ...]) -> float | None:
        label = "|".join(re.escape(item) for item in labels)
        pattern = rf"(?:{label})[^%\d]{{0,100}}(\d{{1,3}}(?:[.,]\d+)?)\s*(?:%|процент\w*)"
        match = re.search(pattern, text, re.I)
        if not match:
            return None
        try:
            value = float(match.group(1).replace(",", "."))
        except ValueError:
            return None
        return value if 0 <= value <= 100 else None

    @staticmethod
    def _extract_days(text: str, labels: tuple[str, ...]) -> int | None:
        label = "|".join(re.escape(item) for item in labels)
        pattern = rf"(?:{label})[^0-9]{{0,100}}(\d{{1,3}})\s*(?:календарн\w*|рабоч\w*)?\s*(?:дн\w*|сут\w*)"
        match = re.search(pattern, text, re.I)
        if not match:
            return None
        try:
            value = int(match.group(1))
        except ValueError:
            return None
        return value if 0 <= value <= 3650 else None

    @property
    def unique_key(self) -> str:
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
        """Полный поисковый текст, включая детали, документы, лоты и спецификации."""
        parts = [self.title, self.description, self.customer, self.region, self.customer_inn]
        raw = self.raw_data or {}
        for key in (
            "details", "lots", "lot", "specification", "specifications", "items", "products",
            "document_text", "document_contents", "attachments_text", "document_search_text",
        ):
            if key in raw:
                parts.extend(self._text_from_value(raw.get(key)))
        if self.documents:
            parts.extend(self._text_from_value(self.documents))
        return " ".join(str(part).strip() for part in parts if part is not None and str(part).strip()).strip()

    @property
    def search_text(self) -> str:
        """Search text excluding document bodies — used when document_search is off."""
        parts = [self.title, self.description, self.customer, self.region, self.customer_inn]
        raw = self.raw_data or {}
        for key in ("details", "lots", "lot", "specification", "specifications", "items", "products"):
            if key in raw:
                parts.extend(self._text_from_value(raw.get(key)))
        return " ".join(str(part).strip() for part in parts if part is not None and str(part).strip()).strip()


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
