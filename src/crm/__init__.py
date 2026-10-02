"""CRM API для управления жизненным циклом тендера."""

from src.storage import (
    ACTIVE_STATUSES,
    ALL_STATUSES,
    ALLOWED_TRANSITIONS,
    BoardEntry,
    InvalidStatusTransition,
    STATUS_ARCHIVED,
    STATUS_EXPIRED,
    TenderBoard,
)

__all__ = [
    "TenderBoard",
    "BoardEntry",
    "InvalidStatusTransition",
    "ALL_STATUSES",
    "ACTIVE_STATUSES",
    "ALLOWED_TRANSITIONS",
    "STATUS_EXPIRED",
    "STATUS_ARCHIVED",
]
