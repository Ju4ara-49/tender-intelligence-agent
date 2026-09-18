"""Tender lifecycle state machine for TenderPlan.

The lifecycle is deliberately separate from task and CRM presentation states.
It models the business state of the tender itself and contains no persistence
or Telegram dependencies.
"""

from __future__ import annotations

from enum import Enum


class TenderLifecycleStatus(str, Enum):
    DISCOVERED = "discovered"
    RELEVANT = "relevant"
    SHORTLISTED = "shortlisted"
    ASSIGNED = "assigned"
    PREPARING = "preparing"
    SUBMITTED = "submitted"
    AUCTION = "auction"
    WON = "won"
    LOST = "lost"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    ARCHIVED = "archived"


TERMINAL_STATUSES = frozenset(
    {
        TenderLifecycleStatus.WON,
        TenderLifecycleStatus.LOST,
        TenderLifecycleStatus.REJECTED,
        TenderLifecycleStatus.CANCELLED,
        TenderLifecycleStatus.EXPIRED,
        TenderLifecycleStatus.ARCHIVED,
    }
)

# Explicit transitions keep accidental state jumps out of the domain.
ALLOWED_TRANSITIONS: dict[TenderLifecycleStatus, frozenset[TenderLifecycleStatus]] = {
    TenderLifecycleStatus.DISCOVERED: frozenset(
        {TenderLifecycleStatus.RELEVANT, TenderLifecycleStatus.REJECTED, TenderLifecycleStatus.CANCELLED, TenderLifecycleStatus.EXPIRED}
    ),
    TenderLifecycleStatus.RELEVANT: frozenset(
        {TenderLifecycleStatus.SHORTLISTED, TenderLifecycleStatus.REJECTED, TenderLifecycleStatus.CANCELLED, TenderLifecycleStatus.EXPIRED}
    ),
    TenderLifecycleStatus.SHORTLISTED: frozenset(
        {TenderLifecycleStatus.ASSIGNED, TenderLifecycleStatus.PREPARING, TenderLifecycleStatus.REJECTED, TenderLifecycleStatus.CANCELLED, TenderLifecycleStatus.EXPIRED}
    ),
    TenderLifecycleStatus.ASSIGNED: frozenset(
        {TenderLifecycleStatus.PREPARING, TenderLifecycleStatus.REJECTED, TenderLifecycleStatus.CANCELLED, TenderLifecycleStatus.EXPIRED}
    ),
    TenderLifecycleStatus.PREPARING: frozenset(
        {TenderLifecycleStatus.SUBMITTED, TenderLifecycleStatus.CANCELLED, TenderLifecycleStatus.EXPIRED}
    ),
    TenderLifecycleStatus.SUBMITTED: frozenset(
        {TenderLifecycleStatus.AUCTION, TenderLifecycleStatus.WON, TenderLifecycleStatus.LOST, TenderLifecycleStatus.CANCELLED}
    ),
    TenderLifecycleStatus.AUCTION: frozenset(
        {TenderLifecycleStatus.WON, TenderLifecycleStatus.LOST, TenderLifecycleStatus.CANCELLED}
    ),
    TenderLifecycleStatus.WON: frozenset({TenderLifecycleStatus.ARCHIVED}),
    TenderLifecycleStatus.LOST: frozenset({TenderLifecycleStatus.ARCHIVED}),
    TenderLifecycleStatus.REJECTED: frozenset({TenderLifecycleStatus.ARCHIVED}),
    TenderLifecycleStatus.CANCELLED: frozenset({TenderLifecycleStatus.ARCHIVED}),
    TenderLifecycleStatus.EXPIRED: frozenset({TenderLifecycleStatus.ARCHIVED}),
    TenderLifecycleStatus.ARCHIVED: frozenset(),
}


class InvalidLifecycleTransition(ValueError):
    """Raised when a tender lifecycle transition is not allowed."""


def can_transition(
    current: TenderLifecycleStatus,
    target: TenderLifecycleStatus,
) -> bool:
    """Return whether *target* is an explicitly allowed next state."""
    return target in ALLOWED_TRANSITIONS[current]


def transition(
    current: TenderLifecycleStatus,
    target: TenderLifecycleStatus,
) -> TenderLifecycleStatus:
    """Validate and return a lifecycle transition."""
    if not can_transition(current, target):
        raise InvalidLifecycleTransition(
            f"invalid tender lifecycle transition: {current.value} -> {target.value}"
        )
    return target


# CRM is a presentation/work-management layer. Some CRM states intentionally
# map to the same business lifecycle state, so the mapping is not reversible.
CRM_TO_LIFECYCLE: dict[str, TenderLifecycleStatus] = {
    "new": TenderLifecycleStatus.DISCOVERED,
    "reviewing": TenderLifecycleStatus.RELEVANT,
    "participating": TenderLifecycleStatus.SHORTLISTED,
    "docs_preparation": TenderLifecycleStatus.PREPARING,
    "submitted": TenderLifecycleStatus.SUBMITTED,
    "waiting_result": TenderLifecycleStatus.AUCTION,
    "won": TenderLifecycleStatus.WON,
    "lost": TenderLifecycleStatus.LOST,
    "skipped": TenderLifecycleStatus.REJECTED,
    "expired": TenderLifecycleStatus.EXPIRED,
    "archived": TenderLifecycleStatus.ARCHIVED,
}


def lifecycle_from_crm(status: str) -> TenderLifecycleStatus:
    """Convert a known CRM status to the corresponding tender lifecycle."""
    key = str(status or "").strip().casefold()
    try:
        return CRM_TO_LIFECYCLE[key]
    except KeyError as exc:
        raise ValueError(f"unknown CRM status: {status!r}") from exc
