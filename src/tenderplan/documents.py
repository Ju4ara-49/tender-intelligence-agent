"""TenderPlan document identity and versioning foundation."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class DocumentExtractionStatus:
    PENDING = "pending"
    EXTRACTED = "extracted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TenderDocument:
    document_id: str
    tender_key: str
    url: str
    filename: str = ""
    content_type: str = ""
    sha256: str = ""
    version: int = 1
    downloaded_at: datetime | None = None
    extraction_status: str = DocumentExtractionStatus.PENDING
    extracted_text: str = ""
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not str(self.document_id).strip():
            raise ValueError("document_id is required")
        if not str(self.tender_key).strip():
            raise ValueError("tender_key is required")
        if not str(self.url).strip():
            raise ValueError("url is required")
        if not self.sha256:
            raise ValueError("sha256 is required")
        if len(self.sha256) != 64:
            raise ValueError("sha256 must be a SHA-256 hex digest")
        if self.version < 1:
            raise ValueError("version must be >= 1")


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class TenderDocumentStore:
    """SQLite store that versions a document URL only when its content changes."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tender_documents (
                    document_id TEXT PRIMARY KEY,
                    tender_key TEXT NOT NULL,
                    url TEXT NOT NULL,
                    filename TEXT NOT NULL DEFAULT '',
                    content_type TEXT NOT NULL DEFAULT '',
                    sha256 TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    downloaded_at TEXT,
                    extraction_status TEXT NOT NULL DEFAULT 'pending',
                    extracted_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(tender_key, url, version),
                    UNIQUE(tender_key, url, sha256)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tender_documents_tender_url "
                "ON tender_documents(tender_key, url, version)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tender_document_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tender_key TEXT NOT NULL,
                    url TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    old_version INTEGER,
                    new_version INTEGER NOT NULL,
                    old_sha256 TEXT,
                    new_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tender_document_events_tender "
                "ON tender_document_events(tender_key, created_at)"
            )
            conn.commit()

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.astimezone(timezone.utc).isoformat() if value else None

    @staticmethod
    def _parse(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value).astimezone(timezone.utc) if value else None

    @staticmethod
    def _from_row(row: sqlite3.Row) -> TenderDocument:
        return TenderDocument(
            document_id=str(row["document_id"]),
            tender_key=str(row["tender_key"]),
            url=str(row["url"]),
            filename=str(row["filename"]),
            content_type=str(row["content_type"]),
            sha256=str(row["sha256"]),
            version=int(row["version"]),
            downloaded_at=TenderDocumentStore._parse(row["downloaded_at"]),
            extraction_status=str(row["extraction_status"]),
            extracted_text=str(row["extracted_text"]),
            created_at=TenderDocumentStore._parse(row["created_at"]),
        )

    def latest(self, tender_key: str, url: str) -> TenderDocument | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tender_documents WHERE tender_key = ? AND url = ? "
                "ORDER BY version DESC LIMIT 1",
                (str(tender_key), str(url)),
            ).fetchone()
        return self._from_row(row) if row else None

    def save(
        self,
        *,
        tender_key: str,
        url: str,
        filename: str = "",
        content_type: str = "",
        sha256: str,
        downloaded_at: datetime | None = None,
        extraction_status: str = DocumentExtractionStatus.PENDING,
        extracted_text: str = "",
    ) -> TenderDocument:
        if len(str(sha256)) != 64:
            raise ValueError("sha256 must be a SHA-256 hex digest")
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM tender_documents WHERE tender_key = ? AND url = ? AND sha256 = ?",
                (str(tender_key), str(url), str(sha256)),
            ).fetchone()
            if existing:
                return self._from_row(existing)

            latest = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM tender_documents "
                "WHERE tender_key = ? AND url = ?",
                (str(tender_key), str(url)),
            ).fetchone()
            version = int(latest["version"]) + 1
            document_id = hashlib.sha256(
                f"{tender_key}\0{url}\0{sha256}".encode("utf-8")
            ).hexdigest()[:32]
            conn.execute(
                """
                INSERT INTO tender_documents
                    (document_id, tender_key, url, filename, content_type, sha256,
                     version, downloaded_at, extraction_status, extracted_text, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    str(tender_key),
                    str(url),
                    str(filename),
                    str(content_type),
                    str(sha256),
                    version,
                    self._iso(downloaded_at or now),
                    str(extraction_status),
                    str(extracted_text or ""),
                    now.isoformat(),
                ),
            )
            old_row = conn.execute(
                "SELECT version, sha256 FROM tender_documents "
                "WHERE tender_key = ? AND url = ? AND version = ?",
                (str(tender_key), str(url), version - 1),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO tender_document_events
                    (tender_key, url, event_type, old_version, new_version,
                     old_sha256, new_sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(tender_key),
                    str(url),
                    "created" if old_row is None else "changed",
                    int(old_row["version"]) if old_row else None,
                    version,
                    str(old_row["sha256"]) if old_row else None,
                    str(sha256),
                    now.isoformat(),
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM tender_documents WHERE document_id = ?", (document_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("document was not persisted")
        return self._from_row(row)

    def list_for_tender(self, tender_key: str) -> list[TenderDocument]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tender_documents WHERE tender_key = ? "
                "ORDER BY url, version",
                (str(tender_key),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def search(self, query: str, tender_key: str | None = None) -> list[TenderDocument]:
        """Search extracted document text deterministically; no AI is required."""
        needle = str(query or "").strip()
        if not needle:
            return []
        # Treat user search text literally: SQL LIKE would otherwise
        # interpret '%' and '_' as wildcards.
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        sql = (
            "SELECT * FROM tender_documents "
            "WHERE extracted_text LIKE ? COLLATE NOCASE ESCAPE '\\\\'"
        )
        params: list[object] = [pattern]
        if tender_key is not None:
            sql += " AND tender_key = ?"
            params.append(str(tender_key))
        sql += " ORDER BY tender_key, url, version DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    def events_for_tender(self, tender_key: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_id, tender_key, url, event_type, old_version, "
                "new_version, old_sha256, new_sha256, created_at "
                "FROM tender_document_events WHERE tender_key = ? "
                "ORDER BY event_id",
                (str(tender_key),),
            ).fetchall()
        return [dict(row) for row in rows]
