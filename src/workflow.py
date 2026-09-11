"""Пользовательский workflow тендера: статус, теги, комментарий и история."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from src.storage.database import TenderDatabase


STATUSES = (
    "new",
    "review",
    "participate",
    "documents",
    "submitted",
    "waiting",
    "won",
    "lost",
    "rejected",
    "ignored",
)
STATUS_NAMES = {
    "new": "Новый",
    "review": "На рассмотрении",
    "participate": "Участвуем",
    "documents": "Документы",
    "submitted": "Подана заявка",
    "waiting": "Ожидаем результат",
    "won": "Выигран",
    "lost": "Проигран",
    "rejected": "Отклонён",
    "ignored": "Игнорируем",
}


@dataclass(frozen=True)
class WorkflowState:
    tender_id: int
    user_id: str
    status: str
    tags: list[str]
    comment: str
    updated_at: str


class TenderWorkflowStore:
    """Изолированное по пользователю состояние тендера.

    Состояние намеренно хранится отдельно от глобальной карточки тендера:
    один и тот же тендер может иметь разные статусы/теги у разных пользователей.
    """

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db
        self._ensure_schema()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _tags(value) -> list[str]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = [value]
        if not isinstance(value, list):
            return []
        result = []
        seen = set()
        for item in value:
            tag = str(item).strip()
            key = tag.casefold()
            if tag and key not in seen:
                seen.add(key)
                result.append(tag[:80])
        return result[:50]

    def _ensure_schema(self) -> None:
        with self.db._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tender_workflow (
                    tender_id INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    tags TEXT NOT NULL DEFAULT '[]',
                    comment TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tender_id, user_id),
                    FOREIGN KEY (tender_id) REFERENCES tenders(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS tender_workflow_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tender_id INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    old_value TEXT NOT NULL DEFAULT '',
                    new_value TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (tender_id) REFERENCES tenders(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_workflow_user_updated
                    ON tender_workflow(user_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_workflow_history_tender_user
                    ON tender_workflow_history(tender_id, user_id, changed_at);
                """
            )

    def _row(self, tender_id: int, user_id: str):
        with self.db._connect() as conn:
            return conn.execute(
                "SELECT * FROM tender_workflow WHERE tender_id = ? AND user_id = ?",
                (int(tender_id), str(user_id).strip()),
            ).fetchone()

    def get(self, tender_id: int, user_id: str | int) -> WorkflowState:
        user_id = str(user_id).strip()
        row = self._row(tender_id, user_id)
        if row is None:
            return WorkflowState(int(tender_id), user_id, "new", [], "", "")
        return WorkflowState(
            tender_id=int(row["tender_id"]), user_id=row["user_id"], status=row["status"],
            tags=self._tags(row["tags"]), comment=row["comment"], updated_at=row["updated_at"],
        )

    def _ensure_row(self, tender_id: int, user_id: str, conn) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO tender_workflow(tender_id, user_id, status, tags, comment, updated_at)
            VALUES (?, ?, 'new', '[]', '', ?)
            """,
            (int(tender_id), user_id, self._now()),
        )

    def set_status(self, tender_id: int, user_id: str | int, status: str) -> WorkflowState:
        status = str(status).strip().lower()
        if status not in STATUSES:
            raise ValueError(f"Неизвестный статус: {status}")
        user_id = str(user_id).strip()
        if not user_id:
            raise ValueError("user_id обязателен")
        with self.db._connect() as conn:
            self._ensure_row(tender_id, user_id, conn)
            old = conn.execute(
                "SELECT status FROM tender_workflow WHERE tender_id = ? AND user_id = ?",
                (int(tender_id), user_id),
            ).fetchone()["status"]
            if old != status:
                now = self._now()
                conn.execute(
                    "UPDATE tender_workflow SET status = ?, updated_at = ? WHERE tender_id = ? AND user_id = ?",
                    (status, now, int(tender_id), user_id),
                )
                conn.execute(
                    "INSERT INTO tender_workflow_history(tender_id, user_id, changed_at, event_type, old_value, new_value) VALUES (?, ?, ?, 'status', ?, ?)",
                    (int(tender_id), user_id, now, old, status),
                )
        return self.get(tender_id, user_id)

    def set_tags(self, tender_id: int, user_id: str | int, tags: list[str]) -> WorkflowState:
        user_id = str(user_id).strip()
        normalized = self._tags(tags)
        with self.db._connect() as conn:
            self._ensure_row(tender_id, user_id, conn)
            old_row = conn.execute(
                "SELECT tags FROM tender_workflow WHERE tender_id = ? AND user_id = ?",
                (int(tender_id), user_id),
            ).fetchone()
            old = self._tags(old_row["tags"])
            if old != normalized:
                now = self._now()
                conn.execute(
                    "UPDATE tender_workflow SET tags = ?, updated_at = ? WHERE tender_id = ? AND user_id = ?",
                    (json.dumps(normalized, ensure_ascii=False), now, int(tender_id), user_id),
                )
                conn.execute(
                    "INSERT INTO tender_workflow_history(tender_id, user_id, changed_at, event_type, old_value, new_value) VALUES (?, ?, ?, 'tags', ?, ?)",
                    (int(tender_id), user_id, now, json.dumps(old, ensure_ascii=False), json.dumps(normalized, ensure_ascii=False)),
                )
        return self.get(tender_id, user_id)

    def set_comment(self, tender_id: int, user_id: str | int, comment: str) -> WorkflowState:
        user_id = str(user_id).strip()
        comment = str(comment or "").strip()[:4000]
        with self.db._connect() as conn:
            self._ensure_row(tender_id, user_id, conn)
            old = conn.execute(
                "SELECT comment FROM tender_workflow WHERE tender_id = ? AND user_id = ?",
                (int(tender_id), user_id),
            ).fetchone()["comment"]
            if old != comment:
                now = self._now()
                conn.execute(
                    "UPDATE tender_workflow SET comment = ?, updated_at = ? WHERE tender_id = ? AND user_id = ?",
                    (comment, now, int(tender_id), user_id),
                )
                conn.execute(
                    "INSERT INTO tender_workflow_history(tender_id, user_id, changed_at, event_type, old_value, new_value) VALUES (?, ?, ?, 'comment', ?, ?)",
                    (int(tender_id), user_id, now, old, comment),
                )
        return self.get(tender_id, user_id)

    def history(self, tender_id: int, user_id: str | int) -> list[dict]:
        with self.db._connect() as conn:
            rows = conn.execute(
                "SELECT id, changed_at, event_type, old_value, new_value FROM tender_workflow_history WHERE tender_id = ? AND user_id = ? ORDER BY changed_at ASC, id ASC",
                (int(tender_id), str(user_id).strip()),
            ).fetchall()
        return [dict(row) for row in rows]
