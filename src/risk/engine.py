"""Детерминированный Risk Engine без LLM."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from src.models.tender import Tender

RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
Severity = Literal["low", "medium", "high"]
_RANK = {"low": 0, "medium": 1, "high": 2}

@dataclass(frozen=True)
class RiskFactor:
    code: str
    severity: Severity
    evidence: str
    source: str
    explanation: str

@dataclass
class RiskAssessment:
    level: RiskLevel
    factors: list[RiskFactor] = field(default_factory=list)
    @property
    def factor_codes(self) -> list[str]:
        return [f.code for f in self.factors]
    def to_dict(self) -> dict:
        return {"level": self.level, "factors": [
            {"code": f.code, "severity": f.severity, "evidence": f.evidence,
             "source": f.source, "explanation": f.explanation} for f in self.factors
        ]}

class RiskEngine:
    SHORT_DEADLINE_HIGH_DAYS = 3.0
    SHORT_DEADLINE_MEDIUM_DAYS = 7.0
    HIGH_APPLICATION_SECURITY_PERCENT = 5.0
    HIGH_CONTRACT_SECURITY_PERCENT = 30.0
    CRITICAL_FIELDS = ("price", "deadline", "customer")

    def assess(self, tender: Tender, *, now: datetime | None = None) -> RiskAssessment:
        moment = now or datetime.now(timezone.utc)
        missing = [name for name, value in (
            ("price", tender.price), ("deadline", tender.deadline), ("customer", tender.customer)
        ) if value is None or value == ""]
        factors: list[RiskFactor] = []
        if missing:
            severity: Severity = "high" if len(missing) >= 2 else "medium"
            factors.append(RiskFactor("insufficient_data", severity, ", ".join(missing), "tender",
                                      f"Отсутствуют ключевые поля тендера: {', '.join(missing)}"))
        if tender.deadline is not None:
            deadline = tender.deadline if tender.deadline.tzinfo else tender.deadline.replace(tzinfo=timezone.utc)
            days = (deadline - moment).total_seconds() / 86400
            if days < 0:
                factors.append(RiskFactor("deadline_passed", "high", deadline.isoformat(), "deadline",
                                          "Срок подачи заявки уже истёк"))
            elif days <= self.SHORT_DEADLINE_HIGH_DAYS:
                factors.append(RiskFactor("short_deadline", "high", f"{days:.1f} дн.", "deadline",
                                          "До окончания подачи заявки осталось не более 3 дней"))
            elif days <= self.SHORT_DEADLINE_MEDIUM_DAYS:
                factors.append(RiskFactor("short_deadline", "medium", f"{days:.1f} дн.", "deadline",
                                          "До окончания подачи заявки осталось не более 7 дней"))
        if tender.application_security_percent is not None and tender.application_security_percent > self.HIGH_APPLICATION_SECURITY_PERCENT:
            factors.append(RiskFactor("high_application_security", "medium",
                                      f"{tender.application_security_percent}%", "application_security_percent",
                                      "Обеспечение заявки превышает 5%"))
        if tender.contract_security_percent is not None and tender.contract_security_percent > self.HIGH_CONTRACT_SECURITY_PERCENT:
            factors.append(RiskFactor("high_contract_security", "medium",
                                      f"{tender.contract_security_percent}%", "contract_security_percent",
                                      "Обеспечение контракта превышает 30%"))
        if tender.advance_required and tender.advance_percent is None:
            factors.append(RiskFactor("unclear_advance", "low", "advance_required=True, advance_percent=None",
                                      "advance_percent", "Аванс заявлен, но точный процент не определён"))
        status = str(tender.detail_status or "").strip().lower()
        if status and status not in {"success", "ok"}:
            factors.append(RiskFactor("incomplete_detail_data", "medium", tender.detail_status, "detail_status",
                                      "Детальная информация о тендере получена не полностью"))
        if len(missing) == len(self.CRITICAL_FIELDS):
            level: RiskLevel = "UNKNOWN"
        elif not factors:
            level = "LOW"
        else:
            worst = max(_RANK[f.severity] for f in factors)
            level = "HIGH" if worst == 2 else "MEDIUM" if worst == 1 else "LOW"
        return RiskAssessment(level=level, factors=factors)
