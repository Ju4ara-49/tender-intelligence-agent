"""Объективный (детерминированный) Risk Engine.

Правило из ТЗ: базовый расчёт риска НЕ использует LLM/Ollama и НЕ оперирует
"вероятностью победы" без статистической модели. Каждый risk factor несёт
code/severity/evidence/source/explanation, а итог — один из уровней
LOW / MEDIUM / HIGH / UNKNOWN.

UNKNOWN используется только тогда, когда данных настолько мало, что даже
базовая оценка ненадёжна (все критичные поля тендера отсутствуют одновременно).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from src.models.tender import Tender

RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
Severity = Literal["low", "medium", "high"]

_SEVERITY_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class RiskFactor:
    """Один объективный признак риска."""
    code: str
    severity: Severity
    evidence: str
    source: str
    explanation: str


@dataclass
class RiskAssessment:
    """Итог оценки риска тендера."""
    level: RiskLevel
    factors: list[RiskFactor] = field(default_factory=list)

    @property
    def factor_codes(self) -> list[str]:
        return [factor.code for factor in self.factors]

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "factors": [
                {
                    "code": factor.code,
                    "severity": factor.severity,
                    "evidence": factor.evidence,
                    "source": factor.source,
                    "explanation": factor.explanation,
                }
                for factor in self.factors
            ],
        }


class RiskEngine:
    """Детерминированный расчёт риска тендера по объективным факторам."""

    SHORT_DEADLINE_HIGH_DAYS: float = 3.0
    SHORT_DEADLINE_MEDIUM_DAYS: float = 7.0
    HIGH_APPLICATION_SECURITY_PERCENT: float = 5.0
    HIGH_CONTRACT_SECURITY_PERCENT: float = 30.0
    CRITICAL_FIELDS: tuple[str, ...] = ("price", "deadline", "customer")
    COMPLETE_DETAIL_STATUSES: frozenset[str] = frozenset({"success", "ok"})

    def assess(self, tender: Tender, *, now: datetime | None = None) -> RiskAssessment:
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        else:
            moment = moment.astimezone(timezone.utc)
        factors: list[RiskFactor] = []
        missing_critical = self._missing_critical_fields(tender)
        factors.extend(self._missing_data_factor(missing_critical))
        factors.extend(self._deadline_factors(tender, moment))
        factors.extend(self._security_factors(tender))
        factors.extend(self._advance_factors(tender))
        factors.extend(self._detail_status_factors(tender))
        return RiskAssessment(level=self._aggregate_level(missing_critical, factors), factors=factors)

    def _missing_critical_fields(self, tender: Tender) -> list[str]:
        missing: list[str] = []
        if tender.price is None:
            missing.append("price")
        if tender.deadline is None:
            missing.append("deadline")
        if not tender.customer:
            missing.append("customer")
        return missing

    def _missing_data_factor(self, missing: list[str]) -> list[RiskFactor]:
        if not missing:
            return []
        severity: Severity = "high" if len(missing) >= 2 else "medium"
        return [RiskFactor("insufficient_data", severity, ", ".join(missing), "tender", f"Отсутствуют ключевые поля тендера: {', '.join(missing)}")]

    def _deadline_factors(self, tender: Tender, now: datetime) -> list[RiskFactor]:
        if tender.deadline is None:
            return []
        deadline = tender.deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        else:
            deadline = deadline.astimezone(timezone.utc)
        remaining_days = (deadline - now).total_seconds() / 86400.0
        if remaining_days < 0:
            return [RiskFactor("deadline_passed", "high", deadline.isoformat(), "deadline", "Срок подачи заявки уже истёк")]
        if remaining_days <= self.SHORT_DEADLINE_HIGH_DAYS:
            return [RiskFactor("short_deadline", "high", f"{remaining_days:.1f} дн. до окончания подачи", "deadline", "До окончания подачи заявки осталось не более 3 дней")]
        if remaining_days <= self.SHORT_DEADLINE_MEDIUM_DAYS:
            return [RiskFactor("short_deadline", "medium", f"{remaining_days:.1f} дн. до окончания подачи", "deadline", "До окончания подачи заявки осталось не более 7 дней")]
        return []

    def _security_factors(self, tender: Tender) -> list[RiskFactor]:
        factors: list[RiskFactor] = []
        if tender.application_security_percent is not None and tender.application_security_percent > self.HIGH_APPLICATION_SECURITY_PERCENT:
            factors.append(RiskFactor("high_application_security", "medium", f"{tender.application_security_percent}%", "application_security_percent", "Обеспечение заявки превышает 5%"))
        if tender.contract_security_percent is not None and tender.contract_security_percent > self.HIGH_CONTRACT_SECURITY_PERCENT:
            factors.append(RiskFactor("high_contract_security", "medium", f"{tender.contract_security_percent}%", "contract_security_percent", "Обеспечение контракта превышает 30%"))
        return factors

    def _advance_factors(self, tender: Tender) -> list[RiskFactor]:
        if tender.advance_required and tender.advance_percent is None:
            return [RiskFactor("unclear_advance", "low", "advance_required=True, advance_percent=None", "advance_percent", "Аванс заявлен в документации, но точный процент не определён")]
        return []

    def _detail_status_factors(self, tender: Tender) -> list[RiskFactor]:
        status = (tender.detail_status or "").strip().lower()
        if status and status not in self.COMPLETE_DETAIL_STATUSES:
            return [RiskFactor("incomplete_detail_data", "medium", tender.detail_status, "detail_status", "Детальная информация о тендере получена не полностью")]
        return []

    def _aggregate_level(self, missing_critical: list[str], factors: list[RiskFactor]) -> RiskLevel:
        if len(missing_critical) >= len(self.CRITICAL_FIELDS):
            return "UNKNOWN"
        if not factors:
            return "LOW"
        worst = max(_SEVERITY_RANK[factor.severity] for factor in factors)
        return "HIGH" if worst == 2 else "MEDIUM" if worst == 1 else "LOW"
