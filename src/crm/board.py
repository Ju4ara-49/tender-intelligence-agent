"""Backward-compatible CRM board import surface.

The canonical implementation lives in src.storage.
Keeping a single implementation prevents the storage and CRM import paths from diverging.
"""
from src.storage import (
    ACTIVE_STATUSES,
    ALL_STATUSES,
    ALLOWED_TRANSITIONS,
    BoardEntry,
    InvalidStatusTransition,
    TenderBoard,
    STATUS_ARCHIVED,
    STATUS_DOCS,
    STATUS_EXPIRED,
    STATUS_LOST,
    STATUS_NEW,
    STATUS_PARTICIPATING,
    STATUS_REVIEWING,
    STATUS_SKIPPED,
    STATUS_SUBMITTED,
    STATUS_WAITING,
    STATUS_WON,
)

__all__ = [
    "TenderBoard", "BoardEntry", "InvalidStatusTransition",
    "ALL_STATUSES", "ACTIVE_STATUSES", "ALLOWED_TRANSITIONS",
    "STATUS_NEW", "STATUS_REVIEWING", "STATUS_PARTICIPATING", "STATUS_DOCS",
    "STATUS_SUBMITTED", "STATUS_WAITING", "STATUS_WON", "STATUS_LOST",
    "STATUS_SKIPPED", "STATUS_EXPIRED", "STATUS_ARCHIVED",
]
