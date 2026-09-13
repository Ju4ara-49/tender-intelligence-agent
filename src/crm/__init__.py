"""CRM-слой: статусы, ответственные, метки и дедлайны тендеров."""

from .board import (
    ACTIVE_STATUSES,
    ALL_STATUSES,
    STATUS_DOCS,
    STATUS_LOST,
    STATUS_NEW,
    STATUS_PARTICIPATING,
    STATUS_REVIEWING,
    STATUS_SKIPPED,
    STATUS_SUBMITTED,
    STATUS_WAITING,
    STATUS_WON,
    BoardEntry,
    InvalidStatusTransition,
    TenderBoard,
)

__all__ = [
    "ACTIVE_STATUSES",
    "ALL_STATUSES",
    "STATUS_DOCS",
    "STATUS_LOST",
    "STATUS_NEW",
    "STATUS_PARTICIPATING",
    "STATUS_REVIEWING",
    "STATUS_SKIPPED",
    "STATUS_SUBMITTED",
    "STATUS_WAITING",
    "STATUS_WON",
    "BoardEntry",
    "InvalidStatusTransition",
    "TenderBoard",
]
