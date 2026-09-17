"""Stable import location for risk persistence.

Kept separate from ``TenderDatabase`` so the deterministic risk domain can be
integrated incrementally without changing existing tender storage semantics.
"""
from src.risk.storage import RiskAssessmentStore

__all__ = ["RiskAssessmentStore"]
