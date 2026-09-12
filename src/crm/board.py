"""Persistent CRM workflow board for tenders."""

from __future__ import annotations

from datetime import datetime, timezone

from src.storage.database import TenderDatabase


class TenderBoard:
    STATUSES = ("new", "reviewing", "participating", "docs_preparation", "submitted", "waiting_result", "won", "lost", "skipped")
    STATUS_LABELS = {
        "new": "Новый", "reviewing": "Проверить", "participating": "Участвуем",
        "docs_preparation": "Документы", "submitted": "Подано", "waiting_result": "Ожидание",
        "won": "Победа", "lost": "Проигрыш", "skipped": "Пропускаем",
    }
    ALLOWED_TRANSITIONS = {
        "new": {"reviewing", "skipped"},
        "reviewing": {"new", "participating", "skipped"},
        "participating": {"reviewing", "docs_preparation", "skipped"},
        "docs_preparation": {"participating", "submitted", "skipped"},
        "submitted": {"participating", "waiting_result"},
        "waiting_result": {"submitted", "won", "lost"},
        "won": {"reviewing"}, "lost": {"reviewing"}, "skipped": {"reviewing"},
    }

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db
        with db._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tender_board (
                    tender_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'new',
                    assignee_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (tender_id) REFERENCES tenders(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS tender_board_labels (
                    tender_id INTEGER NOT NULL,
                    label TEXT NOT NULL COLLATE NOCASE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tender_id, label),
                    FOREIGN KEY (tender_id) REFERENCES tenders(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS tender_board_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tender_id INTEGER NOT NULL,
                    old_status TEXT,
                    new_status TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    FOREIGN KEY (tender_id) REFERENCES tenders(id) ON DELETE CASCADE
                );
            """)

    def ensure(self, tender_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.db._connect() as conn:
            if conn.execute("SELECT 1 FROM tenders WHERE id=?", (tender_id,)).fetchone() is None:
                raise ValueError(f"Tender not found: {tender_id}")
            conn.execute("INSERT OR IGNORE INTO tender_board(tender_id,created_at,updated_at) VALUES(?,?,?)", (tender_id, now, now))

    def status(self, tender_id: int) -> str:
        self.ensure(tender_id)
        with self.db._connect() as conn:
            return str(conn.execute("SELECT status FROM tender_board WHERE tender_id=?", (tender_id,)).fetchone()[0])

    def set_status(self, tender_id: int, new_status: str, force: bool = False) -> str:
        if new_status not in self.STATUSES:
            raise ValueError(f"Unknown board status: {new_status}")
        old_status = self.status(tender_id)
        if old_status == new_status:
            return old_status
        if not force and new_status not in self.ALLOWED_TRANSITIONS[old_status]:
            raise ValueError(f"Недопустимый переход статуса: {old_status} -> {new_status}")
        now = datetime.now(timezone.utc).isoformat()
        with self.db._connect() as conn:
            conn.execute("UPDATE tender_board SET status=?,updated_at=? WHERE tender_id=?", (new_status, now, tender_id))
            conn.execute("INSERT INTO tender_board_history(tender_id,old_status,new_status,changed_at) VALUES(?,?,?,?)", (tender_id, old_status, new_status, now))
        return new_status

    def assign(self, tender_id: int, assignee_id: str | None) -> None:
        self.ensure(tender_id)
        now = datetime.now(timezone.utc).isoformat()
        value = str(assignee_id).strip() if assignee_id else None
        with self.db._connect() as conn:
            conn.execute("UPDATE tender_board SET assignee_id=?,updated_at=? WHERE tender_id=?", (value or None, now, tender_id))

    def add_label(self, tender_id: int, label: str) -> None:
        self.ensure(tender_id)
        label = " ".join(str(label).split()).strip()
        if not label or len(label) > 80:
            raise ValueError("Некорректная метка")
        now = datetime.now(timezone.utc).isoformat()
        with self.db._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO tender_board_labels(tender_id,label,created_at) VALUES(?,?,?)", (tender_id, label, now))

    def remove_label(self, tender_id: int, label: str) -> None:
        with self.db._connect() as conn:
            conn.execute("DELETE FROM tender_board_labels WHERE tender_id=? AND label=? COLLATE NOCASE", (tender_id, " ".join(str(label).split()).strip()))

    def list_by_status(self, status: str) -> list[dict]:
        if status not in self.STATUSES:
            raise ValueError(f"Unknown board status: {status}")
        with self.db._connect() as conn:
            rows = conn.execute("""
                SELECT b.tender_id,b.status,b.assignee_id,t.platform,t.external_id,t.title,t.price,t.customer,t.region,t.deadline,t.end_date,t.url
                FROM tender_board b JOIN tenders t ON t.id=b.tender_id
                WHERE b.status=? ORDER BY COALESCE(t.deadline,t.end_date),b.updated_at
            """, (status,)).fetchall()
            return [dict(row) for row in rows]

    def upcoming_deadlines(self, days: int = 7) -> list[dict]:
        if days < 0 or days > 366:
            raise ValueError("days должен быть от 0 до 366")
        now = datetime.now(timezone.utc)
        limit = now.timestamp() + days * 86400
        with self.db._connect() as conn:
            rows = conn.execute("""
                SELECT b.tender_id,b.status,b.assignee_id,t.platform,t.external_id,t.title,t.price,t.customer,t.region,t.deadline,t.end_date,t.url
                FROM tender_board b JOIN tenders t ON t.id=b.tender_id
                WHERE b.status IN ('new','reviewing','participating','docs_preparation','submitted','waiting_result')
                  AND COALESCE(t.deadline,t.end_date) IS NOT NULL
                  AND strftime('%s',COALESCE(t.deadline,t.end_date)) BETWEEN strftime('%s',?) AND ?
                ORDER BY COALESCE(t.deadline,t.end_date)
            """, (now.isoformat(), int(limit))).fetchall()
            return [dict(row) for row in rows]
