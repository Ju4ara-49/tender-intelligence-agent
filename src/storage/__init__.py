"""Хранение данных."""

from .database import TenderDatabase


def _count_notifications(self: TenderDatabase) -> int:
    """Compatibility API: count persisted recipient-aware delivery events."""
    with self._connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM notification_events").fetchone()
    return int(row["count"]) if row is not None else 0


# Older integrations and regression tests use this public helper. Keep it on
# TenderDatabase while the storage implementation remains centralized in database.py.
if not hasattr(TenderDatabase, "count_notifications"):
    TenderDatabase.count_notifications = _count_notifications

__all__ = ["TenderDatabase"]
