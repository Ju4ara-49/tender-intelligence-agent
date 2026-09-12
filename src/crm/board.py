"""CRM/Kanban слой поверх сохранённых тендеров."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.storage.database import TenderDatabase

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
    STATUS_NEW,
    STATUS_REVIEWING,
    STATUS_PARTICIPATING,
    STATUS_DOCS,
    STATUS_SUBMITTED,
    STATUS_WAITING,
    STATUS_WON,
    STATUS_LOST,
    STATUS_SKIPPED,
)
ACTIVE_STATUSES: frozenset[str] = frozenset(
    {STATUS_REVIEWING, STATUS_PARTICIPATING, STATUS_DOCS, STATUS_SUBMITTED, STATUS_WAITING}
)
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
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


class InvalidStatusTransition(ValueError):
    """Requested status transition is not allowed."""


@dataclass(frozen=True)
class BoardEntry:
    tender_id: int
    status: str
    assignee: str
    labels: list[str]
    updated_at: str


class TenderBoard:
    """Kanban state for tenders stored by TenderDatabase."""

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db
        self._ensure_schema()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_label(label: str) -> str:
        return " ".join(str(label).strip().split())

    def _ensure_schema(self) -> None:
        with self.db._connect() as conn:
            conn.executescript(
                """
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
                CREATE TABLE IF NOT EXISTS tender_board_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tender_id INTEGER NOT NULL,
                    changed_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    old_value TEXT NOT NULL DEFAULT '',
                    new_value TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (tender_id) REFERENCES tenders(id)
                );
                CREATE INDEX IF NOT EXISTS idx_tender_board_status ON tender_board(status);
                CREATE INDEX IF NOT EXISTS idx_tender_labels_tender ON tender_labels(tender_id);
                CREATE INDEX IF NOT EXISTS idx_tender_board_history_tender_changed ON tender_board_history(tender_id, changed_at, id);
                """
            )
            # SQLite's normal UNIQUE constraint is case-sensitive.  The public
            # API treats labels case-insensitively, so enforce that rule in the
            # database as well; this closes the concurrent INSERT race.
            conn.execute(
                """
                DELETE FROM tender_labels
                WHERE id NOT IN (
                    SELECT MIN(id)
                    FROM tender_labels
                    GROUP BY tender_id, label COLLATE NOCASE
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_tender_labels_tender_label_nocase "
                "ON tender_labels(tender_id, label COLLATE NOCASE)"
            )

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in ALL_STATUSES:
            raise ValueError(f"Unknown status: {status!r}")

    @staticmethod
    def _require_tender(conn, tender_id: int) -> None:
        if conn.execute("SELECT 1 FROM tenders WHERE id = ?", (tender_id,)).fetchone() is None:
            raise ValueError(f"Tender not found: {tender_id}")

    def get_status(self, tender_id: int) -> str:
        with self.db._connect() as conn:
            self._require_tender(conn, tender_id)
            row = conn.execute("SELECT status FROM tender_board WHERE tender_id = ?", (tender_id,)).fetchone()
        return str(row["status"]) if row else STATUS_NEW

    def set_status(self, tender_id: int, new_status: str, *, force: bool = False) -> str:
        self._validate_status(new_status)
        now = self._now()
        with self.db._connect() as conn:
            # Status transitions are read-modify-write operations.  Serialize
            # them so two concurrent operators cannot both transition from the
            # same stale status and create contradictory history.
            conn.execute("BEGIN IMMEDIATE")
            self._require_tender(conn, tender_id)
            row = conn.execute("SELECT status, assignee FROM tender_board WHERE tender_id = ?", (tender_id,)).fetchone()
            current = str(row["status"]) if row else STATUS_NEW
            assignee = str(row["assignee"]) if row else ""
            if not force and new_status != current and new_status not in _ALLOWED_TRANSITIONS[current]:
                raise InvalidStatusTransition(f"Cannot move tender {tender_id} from '{current}' to '{new_status}'")
            if row is None:
                conn.execute(
                    "INSERT INTO tender_board (tender_id, status, assignee, updated_at) VALUES (?, ?, ?, ?)",
                    (tender_id, new_status, assignee, now),
                )
            else:
                conn.execute("UPDATE tender_board SET status = ?, updated_at = ? WHERE tender_id = ?", (new_status, now, tender_id))
            if new_status != current:
                conn.execute(
                    "INSERT INTO tender_board_history (tender_id, changed_at, event_type, old_value, new_value) VALUES (?, ?, 'status_changed', ?, ?)",
                    (tender_id, now, current, new_status),
                )
        return new_status

    def assign(self, tender_id: int, assignee: str) -> None:
        normalized = str(assignee).strip()
        if not normalized:
            raise ValueError("Assignee cannot be empty")
        now = self._now()
        with self.db._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_tender(conn, tender_id)
            row = conn.execute("SELECT status, assignee FROM tender_board WHERE tender_id = ?", (tender_id,)).fetchone()
            status = str(row["status"]) if row else STATUS_NEW
            old = str(row["assignee"]) if row else ""
            if row is None:
                conn.execute("INSERT INTO tender_board (tender_id, status, assignee, updated_at) VALUES (?, ?, ?, ?)", (tender_id, status, normalized, now))
            else:
                conn.execute("UPDATE tender_board SET assignee = ?, updated_at = ? WHERE tender_id = ?", (normalized, now, tender_id))
            if old != normalized:
                conn.execute(
                    "INSERT INTO tender_board_history (tender_id, changed_at, event_type, old_value, new_value) VALUES (?, ?, 'assignee_changed', ?, ?)",
                    (tender_id, now, old, normalized),
                )

    def unassign(self, tender_id: int) -> None:
        """Снять ответственного, сохранив запись и историю доски."""
        now = self._now()
        with self.db._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_tender(conn, tender_id)
            row = conn.execute("SELECT status, assignee FROM tender_board WHERE tender_id = ?", (tender_id,)).fetchone()
            if row is None:
                return
            old = str(row["assignee"])
            if not old:
                return
            conn.execute("UPDATE tender_board SET assignee = '', updated_at = ? WHERE tender_id = ?", (now, tender_id))
            conn.execute(
                "INSERT INTO tender_board_history (tender_id, changed_at, event_type, old_value, new_value) VALUES (?, ?, 'assignee_changed', ?, '')",
                (tender_id, now, old),
            )

    def add_label(self, tender_id: int, label: str) -> None:
        normalized = self._normalize_label(label)
        if not normalized:
            return
        now = self._now()
        with self.db._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_tender(conn, tender_id)
            cursor = conn.execute(
                "INSERT OR IGNORE INTO tender_labels (tender_id, label, created_at) VALUES (?, ?, ?)",
                (tender_id, normalized, now),
            )
            if cursor.rowcount:
                conn.execute(
                    "INSERT INTO tender_board_history (tender_id, changed_at, event_type, new_value) VALUES (?, ?, 'label_added', ?)",
                    (tender_id, now, normalized),
                )

    def remove_label(self, tender_id: int, label: str) -> None:
        normalized = self._normalize_label(label)
        if not normalized:
            return
        now = self._now()
        with self.db._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_tender(conn, tender_id)
            row = conn.execute(
                "SELECT id, label FROM tender_labels WHERE tender_id = ? AND label = ? COLLATE NOCASE",
                (tender_id, normalized),
            ).fetchone()
            if row is None:
                return
            conn.execute("DELETE FROM tender_labels WHERE id = ?", (row["id"],))
            conn.execute(
                "INSERT INTO tender_board_history (tender_id, changed_at, event_type, old_value) VALUES (?, ?, 'label_removed', ?)",
                (tender_id, now, str(row["label"])),
            )

    def labels(self, tender_id: int) -> list[str]:
        with self.db._connect() as conn:
            self._require_tender(conn, tender_id)
            rows = conn.execute("SELECT label FROM tender_labels WHERE tender_id = ? ORDER BY label COLLATE NOCASE, id", (tender_id,)).fetchall()
        return [str(row["label"]) for row in rows]

    def entry(self, tender_id: int) -> BoardEntry:
        with self.db._connect() as conn:
            self._require_tender(conn, tender_id)
            row = conn.execute("SELECT status, assignee, updated_at FROM tender_board WHERE tender_id = ?", (tender_id,)).fetchone()
        return BoardEntry(tender_id, str(row["status"]) if row else STATUS_NEW, str(row["assignee"]) if row else "", self.labels(tender_id), str(row["updated_at"]) if row else "")

    def list_by_status(self, status: str) -> list[dict[str, Any]]:
        self._validate_status(status)
        with self.db._connect() as conn:
            rows = conn.execute(
                """
                SELECT t.id, t.title, t.url, t.deadline, t.price, t.customer,
                       COALESCE(b.assignee, '') AS assignee, COALESCE(b.updated_at, '') AS updated_at
                FROM tenders AS t LEFT JOIN tender_board AS b ON b.tender_id = t.id
                WHERE COALESCE(b.status, 'new') = ?
                ORDER BY t.deadline IS NULL, t.deadline ASC, t.id ASC
                """,
                (status,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upcoming_deadlines(self, within_days: int = 3) -> list[dict[str, Any]]:
        if not isinstance(within_days, int) or isinstance(within_days, bool):
            raise TypeError("within_days must be an integer")
        if within_days < 0:
            raise ValueError("within_days must be >= 0")
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(days=within_days)
        statuses = tuple(sorted(ACTIVE_STATUSES))
        placeholders = ",".join("?" for _ in statuses)
        with self.db._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT t.id, t.title, t.url, t.deadline, t.price, t.customer, b.status, b.assignee
                FROM tenders AS t JOIN tender_board AS b ON b.tender_id = t.id
                WHERE b.status IN ({placeholders}) AND t.deadline IS NOT NULL
                  AND t.deadline >= ? AND t.deadline <= ?
                ORDER BY t.deadline ASC, t.id ASC
                """,
                (*statuses, now.isoformat(), horizon.isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]

    def history(self, tender_id: int) -> list[dict[str, Any]]:
        with self.db._connect() as conn:
            self._require_tender(conn, tender_id)
            rows = conn.execute(
                "SELECT id, tender_id, changed_at, event_type, old_value, new_value, metadata "
                "FROM tender_board_history WHERE tender_id = ? ORDER BY changed_at ASC, id ASC",
                (tender_id,),
            ).fetchall()
        return [dict(row) for row in rows]
