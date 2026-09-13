"""CRM API для управления жизненным циклом тендера."""

from src.storage import (
    ACTIVE_STATUSES,
    ALL_STATUSES,
    BoardEntry,
    InvalidStatusTransition,
    TenderBoard,
)

__all__ = [
    "TenderBoard",
    "BoardEntry",
    "InvalidStatusTransition",
    "ALL_STATUSES",
    "ACTIVE_STATUSES",
]
