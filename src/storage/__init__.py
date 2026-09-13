"""Хранение данных и CRM-доска тендеров."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .database import TenderDatabase


class InvalidStatusTransition(ValueError):
    """Запрошен недопустимый переход CRM-статуса."""


STATUS_NEW = "new"
STATUS_REVIEWING = "reviewing"
STATUS_PARTICIPATING = "participating"
STATUS_DOCS = "docs_preparation"
STATUS_SUBMITTED = "submitted"
STATUS_WAITING = "waiting_result"
STATUS_WON = "won"
STATUS_LOST = "lost"
STATUS_SKIPPED = "skipped"

ALL_STATUSES: tuple[str, ...] = (
    STATUS_NEW, STATUS_REVIEWING, STATUS_PARTICIPATING, STATUS_DOCS,
    STATUS_SUBMITTED, STATUS_WAITING, STATUS_WON, STATUS_LOST, STATUS_SKIPPED,
)
ACTIVE_STATUSES = frozenset({STATUS_REVIEWING, STATUS_PARTICIPATING, STATUS_DOCS, STATUS_SUBMITTED, STATUS_WAITING})
ALLOWED_TRANSITIONS = {
    STATUS_NEW: frozenset({STATUS_REVIEWING, STATUS_SKIPPED}),
    STATUS_REVIEWING: frozenset({STATUS_PARTICIPATING, STATUS_SKIPPED}),
    STATUS_PARTICIPATING: frozenset({STATUS_DOCS, STATUS_SKIPPED, STATUS_REVIEWING}),
    STATUS_DOCS: frozenset({STATUS_SUBMITTED, STATUS_SKIPPED, STATUS_PARTICIPATING}),
    STATUS_SUBMITTED: frozenset({STATUS_WAITING, STATUS_SKIPPED}),
    STATUS_WAITING: frozenset({STATUS_WON, STATUS_LOST, STATUS_SUBMITTED}),
    STATUS_WON: frozenset(),
    STATUS_LOST: frozenset({STATUS_REVIEWING}),
    STATUS_SKIPPED: frozenset({STATUS_REVIEWING}),
}


@dataclass(frozen=True)
class BoardEntry:
    tender_id: int
    status: str
    assignee: str
    labels: list[str]
    updated_at: str


class TenderBoard:
    """Kanban CRM поверх существующего SQLite-хранилища."""

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db
        self._ensure_schema()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _ensure_schema(self) -> None:
        with self.db._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tender_board (
                    tender_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'new',
                    assignee TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (tender_id) REFERENCES tenders(id)
                );
                CREATE TABLE IF NOT EXISTS tender_labels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tender_id INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(tender_id, label),
                    FOREIGN KEY (tender_id) REFERENCES tenders(id)
                );
                CREATE INDEX IF NOT EXISTS idx_tender_board_status ON tender_board(status);
                CREATE INDEX IF NOT EXISTS idx_tender_labels_tender ON tender_labels(tender_id);
            """)

    def _require_tender(self, tender_id: int) -> None:
        if not isinstance(tender_id, int) or isinstance(tender_id, bool) or tender_id <= 0:
            raise ValueError(f"Invalid tender_id: {tender_id!r}")
        with self.db._connect() as conn:
            if conn.execute("SELECT 1 FROM tenders WHERE id = ?", (tender_id,)).fetchone() is None:
                raise ValueError(f"Tender not found: {tender_id}")

    def get_status(self, tender_id: int) -> str:
        self._require_tender(tender_id)
        with self.db._connect() as conn:
            row = conn.execute("SELECT status FROM tender_board WHERE tender_id = ?", (tender_id,)).fetchone()
        return str(row["status"]) if row else STATUS_NEW

    def set_status(self, tender_id: int, new_status: str, *, force: bool = False) -> str:
        self._require_tender(tender_id)
        if new_status not in ALL_STATUSES:
            raise ValueError(f"Unknown status: {new_status!r}")
        current = self.get_status(tender_id)
        if not force and new_status != current and new_status not in ALLOWED_TRANSITIONS[current]:
            raise InvalidStatusTransition(f"Cannot move tender {tender_id} from '{current}' to '{new_status}'")
        with self.db._connect() as conn:
            conn.execute("""
                INSERT INTO tender_board (tender_id, status, assignee, updated_at)
                VALUES (?, ?, '', ?)
                ON CONFLICT(tender_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at
            """, (tender_id, new_status, self._now()))
        return new_status

    def assign(self, tender_id: int, assignee: str) -> None:
        self._require_tender(tender_id)
        if not isinstance(assignee, str):
            raise TypeError("assignee must be a string")
        with self.db._connect() as conn:
            conn.execute("""
                INSERT INTO tender_board (tender_id, status, assignee, updated_at)
                VALUES (?, 'new', ?, ?)
                ON CONFLICT(tender_id) DO UPDATE SET assignee=excluded.assignee, updated_at=excluded.updated_at
            """, (tender_id, assignee.strip(), self._now()))

    def add_label(self, tender_id: int, label: str) -> None:
        self._require_tender(tender_id)
        if not isinstance(label, str):
            raise TypeError("label must be a string")
        label = label.strip()
        if not label:
            return
        with self.db._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO tender_labels (tender_id, label, created_at) VALUES (?, ?, ?)", (tender_id, label, self._now()))

    def remove_label(self, tender_id: int, label: str) -> None:
        self._require_tender(tender_id)
        if not isinstance(label, str):
            raise TypeError("label must be a string")
        with self.db._connect() as conn:
            conn.execute("DELETE FROM tender_labels WHERE tender_id = ? AND label = ?", (tender_id, label.strip()))

    def labels(self, tender_id: int) -> list[str]:
        self._require_tender(tender_id)
        with self.db._connect() as conn:
            rows = conn.execute("SELECT label FROM tender_labels WHERE tender_id = ? ORDER BY label", (tender_id,)).fetchall()
        return [str(row["label"]) for row in rows]

    def entry(self, tender_id: int) -> BoardEntry:
        self._require_tender(tender_id)
        with self.db._connect() as conn:
            row = conn.execute("SELECT status, assignee, updated_at FROM tender_board WHERE tender_id = ?", (tender_id,)).fetchone()
        return BoardEntry(tender_id, str(row["status"]) if row else STATUS_NEW, str(row["assignee"]) if row else "", self.labels(tender_id), str(row["updated_at"]) if row else "")

    def list_by_status(self, status: str) -> list[dict[str, Any]]:
        if status not in ALL_STATUSES:
            raise ValueError(f"Unknown status: {status!r}")
        with self.db._connect() as conn:
            rows = conn.execute("""
                SELECT t.id, t.title, t.url, t.deadline, t.price, t.customer,
                       COALESCE(b.assignee, '') AS assignee, b.updated_at
                FROM tenders t LEFT JOIN tender_board b ON b.tender_id=t.id
                WHERE COALESCE(b.status, 'new')=? ORDER BY t.deadline IS NULL, t.deadline ASC, t.id ASC
            """, (status,)).fetchall()
        result=[]
        for row in rows:
            item=dict(row); item["labels"]=self.labels(int(item["id"])); result.append(item)
        return result

    def upcoming_deadlines(self, within_days: int = 3) -> list[dict[str, Any]]:
        if not isinstance(within_days, int) or isinstance(within_days, bool):
            raise TypeError("within_days must be an integer")
        if within_days < 0:
            raise ValueError("within_days must be >= 0")
        now=datetime.now(timezone.utc); horizon=now+timedelta(days=within_days)
        statuses=tuple(sorted(ACTIVE_STATUSES)); placeholders=','.join('?' for _ in statuses)
        with self.db._connect() as conn:
            rows=conn.execute(f"""
                SELECT t.id, t.title, t.url, t.deadline, t.price, t.customer, b.status, b.assignee
                FROM tenders t JOIN tender_board b ON b.tender_id=t.id
                WHERE b.status IN ({placeholders}) AND t.deadline IS NOT NULL AND t.deadline>=? AND t.deadline<=?
                ORDER BY t.deadline ASC, t.id ASC
            """, (*statuses, now.isoformat(), horizon.isoformat())).fetchall()
        result=[]
        for row in rows:
            item=dict(row); item["labels"]=self.labels(int(item["id"])); result.append(item)
        return result


__all__ = [
    "TenderDatabase", "TenderBoard", "BoardEntry", "InvalidStatusTransition",
    "ALL_STATUSES", "ACTIVE_STATUSES", "STATUS_NEW", "STATUS_REVIEWING",
    "STATUS_PARTICIPATING", "STATUS_DOCS", "STATUS_SUBMITTED", "STATUS_WAITING",
    "STATUS_WON", "STATUS_LOST", "STATUS_SKIPPED",
]
