from __future__ import annotations

import json
from dataclasses import dataclass

from src.storage.database import TenderDatabase


@dataclass
class TenderCriteria:
    min_price: float | None = None
    max_price: float | None = None

    advance_required: bool = False
    min_advance_percent: float = 0.0

    max_postpayment_days: int | None = None

    min_submission_days: int = 7

    min_application_security_percent: float = 0.0
    max_application_security_percent: float | None = 5.0

    min_contract_security_percent: float = 0.0
    max_contract_security_percent: float | None = None

    min_ai_score: int = 70


class CriteriaStore:
    """Хранение пользовательских критериев Telegram в SQLite."""

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.db._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tender_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),

                    min_price REAL,
                    max_price REAL,

                    advance_required INTEGER NOT NULL DEFAULT 0,
                    min_advance_percent REAL NOT NULL DEFAULT 0,

                    max_postpayment_days INTEGER,

                    min_submission_days INTEGER NOT NULL DEFAULT 7,

                    min_application_security_percent REAL NOT NULL DEFAULT 0,
                    max_application_security_percent REAL,

                    min_contract_security_percent REAL NOT NULL DEFAULT 0,
                    max_contract_security_percent REAL,

                    min_ai_score INTEGER NOT NULL DEFAULT 70,

                    keywords TEXT,
                    enabled_platforms TEXT,

                    updated_at TEXT NOT NULL
                )
                """
            )

            # Миграция существующей БД.
            columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(tender_settings)"
                ).fetchall()
            }

            if "keywords" not in columns:
                conn.execute(
                    "ALTER TABLE tender_settings ADD COLUMN keywords TEXT"
                )

            if "enabled_platforms" not in columns:
                conn.execute(
                    "ALTER TABLE tender_settings ADD COLUMN enabled_platforms TEXT"
                )

            conn.execute(
                """
                INSERT OR IGNORE INTO tender_settings (
                    id,
                    min_submission_days,
                    max_application_security_percent,
                    min_ai_score,
                    keywords,
                    enabled_platforms,
                    updated_at
                )
                VALUES (
                    1,
                    7,
                    5,
                    70,
                    NULL,
                    '["eis"]',
                    datetime('now')
                )
                """
            )

    def get(self) -> TenderCriteria:
        with self.db._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tender_settings WHERE id = 1"
            ).fetchone()

        if row is None:
            return TenderCriteria()

        return TenderCriteria(
            min_price=row["min_price"],
            max_price=row["max_price"],
            advance_required=bool(row["advance_required"]),
            min_advance_percent=float(row["min_advance_percent"]),
            max_postpayment_days=row["max_postpayment_days"],
            min_submission_days=int(row["min_submission_days"]),
            min_application_security_percent=float(
                row["min_application_security_percent"]
            ),
            max_application_security_percent=row[
                "max_application_security_percent"
            ],
            min_contract_security_percent=float(
                row["min_contract_security_percent"]
            ),
            max_contract_security_percent=row[
                "max_contract_security_percent"
            ],
            min_ai_score=int(row["min_ai_score"]),
        )

    def update(self, **values) -> None:
        allowed = {
            "min_price",
            "max_price",
            "advance_required",
            "min_advance_percent",
            "max_postpayment_days",
            "min_submission_days",
            "min_application_security_percent",
            "max_application_security_percent",
            "min_contract_security_percent",
            "max_contract_security_percent",
            "min_ai_score",
        }

        values = {
            key: value
            for key, value in values.items()
            if key in allowed
        }

        if not values:
            return

        values["updated_at"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()

        fields = ", ".join(f"{key} = ?" for key in values)

        with self.db._connect() as conn:
            conn.execute(
                f"""
                UPDATE tender_settings
                SET {fields}
                WHERE id = 1
                """,
                tuple(values.values()),
            )

    def get_keywords(self) -> list[str] | None:
        with self.db._connect() as conn:
            row = conn.execute(
                "SELECT keywords FROM tender_settings WHERE id = 1"
            ).fetchone()

        if row is None or not row["keywords"]:
            return None

        try:
            data = json.loads(row["keywords"])
            if isinstance(data, list):
                return [
                    str(item).strip()
                    for item in data
                    if str(item).strip()
                ]
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

        return None

    def set_keywords(self, keywords: list[str]) -> None:
        clean = []
        seen = set()

        for keyword in keywords:
            value = str(keyword).strip()
            if value and value.lower() not in seen:
                clean.append(value)
                seen.add(value.lower())

        with self.db._connect() as conn:
            conn.execute(
                """
                UPDATE tender_settings
                SET keywords = ?, updated_at = datetime('now')
                WHERE id = 1
                """,
                (json.dumps(clean, ensure_ascii=False),),
            )

    def get_enabled_platforms(self) -> list[str]:
        with self.db._connect() as conn:
            row = conn.execute(
                "SELECT enabled_platforms FROM tender_settings WHERE id = 1"
            ).fetchone()

        if row is None or not row["enabled_platforms"]:
            return ["eis"]

        try:
            data = json.loads(row["enabled_platforms"])
            if isinstance(data, list):
                return [str(x) for x in data]
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

        return ["eis"]

    def set_enabled_platforms(self, platforms: list[str]) -> None:
        clean = list(dict.fromkeys(str(x) for x in platforms))

        with self.db._connect() as conn:
            conn.execute(
                """
                UPDATE tender_settings
                SET enabled_platforms = ?, updated_at = datetime('now')
                WHERE id = 1
                """,
                (json.dumps(clean, ensure_ascii=False),),
            )
