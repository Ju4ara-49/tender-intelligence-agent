from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.storage.database import TenderDatabase


SUPPORTED_PLATFORMS = ["eis", "b2b_center", "fabrikant", "rts_tender", "tmk", "rosatom"]


def _clean_list(value: list[str] | None) -> list[str]:
    if not value:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        key = text.casefold()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
    return result


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
    exclude_keywords: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Reject contradictory numeric ranges before they reach the search pipeline."""
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("min_price не может быть больше max_price")
        if self.min_advance_percent < 0:
            raise ValueError("min_advance_percent не может быть отрицательным")
        if self.max_postpayment_days is not None and self.max_postpayment_days < 0:
            raise ValueError("max_postpayment_days не может быть отрицательным")
        if self.min_submission_days < 0:
            raise ValueError("min_submission_days не может быть отрицательным")
        if self.min_application_security_percent < 0:
            raise ValueError("min_application_security_percent не может быть отрицательным")
        if self.max_application_security_percent is not None and self.max_application_security_percent < 0:
            raise ValueError("max_application_security_percent не может быть отрицательным")
        if (
            self.max_application_security_percent is not None
            and self.min_application_security_percent > self.max_application_security_percent
        ):
            raise ValueError("min_application_security_percent не может быть больше max_application_security_percent")
        if self.min_contract_security_percent < 0:
            raise ValueError("min_contract_security_percent не может быть отрицательным")
        if (
            self.max_contract_security_percent is not None
            and self.max_contract_security_percent < 0
        ):
            raise ValueError("max_contract_security_percent не может быть отрицательным")
        if (
            self.max_contract_security_percent is not None
            and self.min_contract_security_percent > self.max_contract_security_percent
        ):
            raise ValueError("min_contract_security_percent не может быть больше max_contract_security_percent")
        self.min_ai_score = max(0, min(100, int(self.min_ai_score)))
        self.exclude_keywords = _clean_list(self.exclude_keywords)
        self.regions = _clean_list(self.regions)


class CriteriaStore:
    """Хранение критериев Telegram отдельно для каждого пользователя."""

    USERS_TABLE = "tender_settings_users"
    DEFAULT_USER_ID = "default"

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db
        self._ensure_schema()

    @classmethod
    def normalize_user_id(cls, user_id: str | int | None) -> str:
        value = str(user_id).strip() if user_id is not None else ""
        return value or cls.DEFAULT_USER_ID

    def set_user_id(self, user_id: str | int | None) -> None:
        return None

    def _ensure_schema(self) -> None:
        with self.db._connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.USERS_TABLE} (
                    user_id TEXT PRIMARY KEY,
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
                    exclude_keywords TEXT NOT NULL DEFAULT '[]',
                    regions TEXT NOT NULL DEFAULT '[]',
                    enabled_platforms TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({self.USERS_TABLE})").fetchall()}
            for column, definition in (("exclude_keywords", "TEXT NOT NULL DEFAULT '[]'"), ("regions", "TEXT NOT NULL DEFAULT '[]'")):
                if column not in columns:
                    conn.execute(f"ALTER TABLE {self.USERS_TABLE} ADD COLUMN {column} {definition}")
            old_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tender_settings'").fetchone()
            if old_exists:
                old_row = conn.execute("SELECT * FROM tender_settings WHERE id = 1").fetchone()
                if old_row is not None:
                    conn.execute(
                        f"""
                        INSERT OR IGNORE INTO {self.USERS_TABLE} (
                            user_id, min_price, max_price, advance_required, min_advance_percent,
                            max_postpayment_days, min_submission_days, min_application_security_percent,
                            max_application_security_percent, min_contract_security_percent,
                            max_contract_security_percent, min_ai_score, keywords, exclude_keywords,
                            regions, enabled_platforms, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            self.DEFAULT_USER_ID, old_row["min_price"], old_row["max_price"], old_row["advance_required"],
                            old_row["min_advance_percent"], old_row["max_postpayment_days"], old_row["min_submission_days"],
                            old_row["min_application_security_percent"], old_row["max_application_security_percent"],
                            old_row["min_contract_security_percent"], old_row["max_contract_security_percent"],
                            old_row["min_ai_score"], old_row["keywords"], "[]", "[]",
                            json.dumps(SUPPORTED_PLATFORMS, ensure_ascii=False), old_row["updated_at"],
                        ),
                    )

    def _ensure_user(self, user_id: str) -> None:
        with self.db._connect() as conn:
            row = conn.execute(f"SELECT 1 FROM {self.USERS_TABLE} WHERE user_id = ?", (user_id,)).fetchone()
            if row is not None:
                return
            source = conn.execute(f"SELECT * FROM {self.USERS_TABLE} WHERE user_id = ?", (self.DEFAULT_USER_ID,)).fetchone()
            if source is None:
                conn.execute(
                    f"INSERT INTO {self.USERS_TABLE} (user_id, min_submission_days, max_application_security_percent, min_ai_score, exclude_keywords, regions, enabled_platforms, updated_at) VALUES (?, 7, 5, 70, '[]', '[]', ?, ?)",
                    (user_id, json.dumps(SUPPORTED_PLATFORMS, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
                )
            else:
                conn.execute(
                    f"""
                    INSERT INTO {self.USERS_TABLE} (
                        user_id, min_price, max_price, advance_required, min_advance_percent,
                        max_postpayment_days, min_submission_days, min_application_security_percent,
                        max_application_security_percent, min_contract_security_percent,
                        max_contract_security_percent, min_ai_score, keywords, exclude_keywords,
                        regions, enabled_platforms, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id, source["min_price"], source["max_price"], source["advance_required"], source["min_advance_percent"],
                        source["max_postpayment_days"], source["min_submission_days"], source["min_application_security_percent"],
                        source["max_application_security_percent"], source["min_contract_security_percent"],
                        source["max_contract_security_percent"], source["min_ai_score"], source["keywords"],
                        source["exclude_keywords"] if source["exclude_keywords"] is not None else "[]",
                        source["regions"] if source["regions"] is not None else "[]",
                        source["enabled_platforms"] if source["enabled_platforms"] is not None else json.dumps(SUPPORTED_PLATFORMS, ensure_ascii=False),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    def _user_id_and_ensure(self, user_id: str | int | None) -> str:
        normalized = self.normalize_user_id(user_id)
        self._ensure_user(normalized)
        return normalized

    def get(self, user_id: str | int | None = None) -> TenderCriteria:
        user_id = self._user_id_and_ensure(user_id)
        with self.db._connect() as conn:
            row = conn.execute(f"SELECT * FROM {self.USERS_TABLE} WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return TenderCriteria()
        return TenderCriteria(
            min_price=row["min_price"], max_price=row["max_price"], advance_required=bool(row["advance_required"]),
            min_advance_percent=float(row["min_advance_percent"]), max_postpayment_days=row["max_postpayment_days"],
            min_submission_days=int(row["min_submission_days"]), min_application_security_percent=float(row["min_application_security_percent"]),
            max_application_security_percent=row["max_application_security_percent"], min_contract_security_percent=float(row["min_contract_security_percent"]),
            max_contract_security_percent=row["max_contract_security_percent"], min_ai_score=int(row["min_ai_score"]),
            exclude_keywords=self._loads(row["exclude_keywords"]), regions=self._loads(row["regions"]),
        )

    @staticmethod
    def _loads(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            data = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return _clean_list(data) if isinstance(data, list) else []

    def update(self, user_id: str | int | None = None, **values) -> None:
        allowed = {"min_price", "max_price", "advance_required", "min_advance_percent", "max_postpayment_days", "min_submission_days", "min_application_security_percent", "max_application_security_percent", "min_contract_security_percent", "max_contract_security_percent", "min_ai_score"}
        values = {key: value for key, value in values.items() if key in allowed}
        if not values:
            return
        user_id = self._user_id_and_ensure(user_id)
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        fields = ", ".join(f"{key} = ?" for key in values)
        with self.db._connect() as conn:
            conn.execute(f"UPDATE {self.USERS_TABLE} SET {fields} WHERE user_id = ?", (*values.values(), user_id))

    def get_keywords(self, user_id: str | int | None = None) -> list[str] | None:
        user_id = self._user_id_and_ensure(user_id)
        with self.db._connect() as conn:
            row = conn.execute(f"SELECT keywords FROM {self.USERS_TABLE} WHERE user_id = ?", (user_id,)).fetchone()
        if row is None or not row["keywords"]:
            return None
        return self._loads(row["keywords"])

    def set_keywords(self, user_id: str | int | None, keywords: list[str]) -> None:
        user_id = self._user_id_and_ensure(user_id)
        with self.db._connect() as conn:
            conn.execute(f"UPDATE {self.USERS_TABLE} SET keywords = ?, updated_at = ? WHERE user_id = ?", (json.dumps(_clean_list(keywords), ensure_ascii=False), datetime.now(timezone.utc).isoformat(), user_id))

    def get_exclude_keywords(self, user_id: str | int | None = None) -> list[str]:
        user_id = self._user_id_and_ensure(user_id)
        with self.db._connect() as conn:
            row = conn.execute(f"SELECT exclude_keywords FROM {self.USERS_TABLE} WHERE user_id = ?", (user_id,)).fetchone()
        return self._loads(row["exclude_keywords"] if row else None)

    def set_exclude_keywords(self, user_id: str | int | None, keywords: list[str]) -> None:
        user_id = self._user_id_and_ensure(user_id)
        with self.db._connect() as conn:
            conn.execute(f"UPDATE {self.USERS_TABLE} SET exclude_keywords = ?, updated_at = ? WHERE user_id = ?", (json.dumps(_clean_list(keywords), ensure_ascii=False), datetime.now(timezone.utc).isoformat(), user_id))

    def get_regions(self, user_id: str | int | None = None) -> list[str]:
        user_id = self._user_id_and_ensure(user_id)
        with self.db._connect() as conn:
            row = conn.execute(f"SELECT regions FROM {self.USERS_TABLE} WHERE user_id = ?", (user_id,)).fetchone()
        return self._loads(row["regions"] if row else None)

    def set_regions(self, user_id: str | int | None, regions: list[str]) -> None:
        user_id = self._user_id_and_ensure(user_id)
        with self.db._connect() as conn:
            conn.execute(f"UPDATE {self.USERS_TABLE} SET regions = ?, updated_at = ? WHERE user_id = ?", (json.dumps(_clean_list(regions), ensure_ascii=False), datetime.now(timezone.utc).isoformat(), user_id))

    def get_enabled_platforms(self, user_id: str | int | None = None) -> list[str]:
        user_id = self._user_id_and_ensure(user_id)
        with self.db._connect() as conn:
            row = conn.execute(f"SELECT enabled_platforms FROM {self.USERS_TABLE} WHERE user_id = ?", (user_id,)).fetchone()
        if row is None or row["enabled_platforms"] is None:
            return list(SUPPORTED_PLATFORMS)
        try:
            data = json.loads(row["enabled_platforms"])
            if isinstance(data, list):
                clean = []
                changed = False
                for item in data:
                    value = str(item).strip()
                    if value == "unipro":
                        value = "fabrikant"
                        changed = True
                    if value in SUPPORTED_PLATFORMS and value not in clean:
                        clean.append(value)
                if changed:
                    with self.db._connect() as write_conn:
                        write_conn.execute(f"UPDATE {self.USERS_TABLE} SET enabled_platforms = ?, updated_at = ? WHERE user_id = ?", (json.dumps(clean, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), user_id))
                return clean
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return list(SUPPORTED_PLATFORMS)

    def set_enabled_platforms(self, user_id: str | int | None, platforms: list[str]) -> None:
        user_id = self._user_id_and_ensure(user_id)
        clean = [x for x in dict.fromkeys(str(x).strip() for x in platforms) if x in SUPPORTED_PLATFORMS]
        with self.db._connect() as conn:
            conn.execute(f"UPDATE {self.USERS_TABLE} SET enabled_platforms = ?, updated_at = ? WHERE user_id = ?", (json.dumps(clean, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), user_id))
