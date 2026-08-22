from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from src.storage.database import TenderDatabase


SUPPORTED_PLATFORMS = ["eis", "b2b_center", "unipro", "rts_tender", "tmk", "rosatom"]


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
    """Хранение критериев Telegram отдельно для каждого пользователя."""

    USERS_TABLE = "tender_settings_users"
    DEFAULT_USER_ID = "default"

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db
        self._ensure_schema()

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
                    enabled_platforms TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

            old_exists = conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'tender_settings'
                """
            ).fetchone()

            if old_exists:
                old_row = conn.execute("SELECT * FROM tender_settings WHERE id = 1").fetchone()
                if old_row is not None:
                    conn.execute(
                        f"""
                        INSERT OR IGNORE INTO {self.USERS_TABLE} (
                            user_id, min_price, max_price,
                            advance_required, min_advance_percent,
                            max_postpayment_days, min_submission_days,
                            min_application_security_percent,
                            max_application_security_percent,
                            min_contract_security_percent,
                            max_contract_security_percent,
                            min_ai_score, keywords, enabled_platforms,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            self.DEFAULT_USER_ID,
                            old_row["min_price"], old_row["max_price"],
                            old_row["advance_required"], old_row["min_advance_percent"],
                            old_row["max_postpayment_days"], old_row["min_submission_days"],
                            old_row["min_application_security_percent"],
                            old_row["max_application_security_percent"],
                            old_row["min_contract_security_percent"],
                            old_row["max_contract_security_percent"],
                            old_row["min_ai_score"], old_row["keywords"],
                            json.dumps(SUPPORTED_PLATFORMS, ensure_ascii=False),
                            old_row["updated_at"],
                        ),
                    )

    def _current_user_id(self) -> str:
        frame = inspect.currentframe()
        try:
            frame = frame.f_back if frame else None
            while frame is not None:
                value = frame.f_locals.get("chat_id")
                if value is not None:
                    value = str(value).strip()
                    if value:
                        return value
                frame = frame.f_back
        finally:
            del frame
        return self.DEFAULT_USER_ID

    def _ensure_user(self, user_id: str) -> None:
        with self.db._connect() as conn:
            row = conn.execute(
                f"SELECT 1 FROM {self.USERS_TABLE} WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row is not None:
                return

            source = conn.execute(
                f"SELECT * FROM {self.USERS_TABLE} WHERE user_id = ?", (self.DEFAULT_USER_ID,)
            ).fetchone()

            if source is None:
                conn.execute(
                    f"""
                    INSERT INTO {self.USERS_TABLE} (
                        user_id, min_submission_days,
                        max_application_security_percent,
                        min_ai_score, enabled_platforms, updated_at
                    ) VALUES (?, 7, 5, 70, ?, ?)
                    """,
                    (user_id, json.dumps(SUPPORTED_PLATFORMS, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
                )
            else:
                conn.execute(
                    f"""
                    INSERT INTO {self.USERS_TABLE} (
                        user_id, min_price, max_price,
                        advance_required, min_advance_percent,
                        max_postpayment_days, min_submission_days,
                        min_application_security_percent,
                        max_application_security_percent,
                        min_contract_security_percent,
                        max_contract_security_percent,
                        min_ai_score, keywords, enabled_platforms,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id, source["min_price"], source["max_price"],
                        source["advance_required"], source["min_advance_percent"],
                        source["max_postpayment_days"], source["min_submission_days"],
                        source["min_application_security_percent"],
                        source["max_application_security_percent"],
                        source["min_contract_security_percent"],
                        source["max_contract_security_percent"], source["min_ai_score"],
                        source["keywords"], source["enabled_platforms"] or json.dumps(SUPPORTED_PLATFORMS, ensure_ascii=False),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    def _user_id_and_ensure(self) -> str:
        user_id = self._current_user_id()
        self._ensure_user(user_id)
        return user_id

    def get(self) -> TenderCriteria:
        user_id = self._user_id_and_ensure()
        with self.db._connect() as conn:
            row = conn.execute(f"SELECT * FROM {self.USERS_TABLE} WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return TenderCriteria()
        return TenderCriteria(
            min_price=row["min_price"], max_price=row["max_price"],
            advance_required=bool(row["advance_required"]),
            min_advance_percent=float(row["min_advance_percent"]),
            max_postpayment_days=row["max_postpayment_days"],
            min_submission_days=int(row["min_submission_days"]),
            min_application_security_percent=float(row["min_application_security_percent"]),
            max_application_security_percent=row["max_application_security_percent"],
            min_contract_security_percent=float(row["min_contract_security_percent"]),
            max_contract_security_percent=row["max_contract_security_percent"],
            min_ai_score=int(row["min_ai_score"]),
        )

    def update(self, **values) -> None:
        allowed = {
            "min_price", "max_price", "advance_required", "min_advance_percent",
            "max_postpayment_days", "min_submission_days",
            "min_application_security_percent", "max_application_security_percent",
            "min_contract_security_percent", "max_contract_security_percent", "min_ai_score",
        }
        values = {key: value for key, value in values.items() if key in allowed}
        if not values:
            return
        user_id = self._user_id_and_ensure()
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        fields = ", ".join(f"{key} = ?" for key in values)
        with self.db._connect() as conn:
            conn.execute(f"UPDATE {self.USERS_TABLE} SET {fields} WHERE user_id = ?", (*values.values(), user_id))

    def get_keywords(self) -> list[str] | None:
        user_id = self._user_id_and_ensure()
        with self.db._connect() as conn:
            row = conn.execute(f"SELECT keywords FROM {self.USERS_TABLE} WHERE user_id = ?", (user_id,)).fetchone()
        if row is None or not row["keywords"]:
            return None
        try:
            data = json.loads(row["keywords"])
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return None

    def set_keywords(self, keywords: list[str]) -> None:
        user_id = self._user_id_and_ensure()
        clean, seen = [], set()
        for keyword in keywords:
            value = str(keyword).strip()
            if value and value.lower() not in seen:
                clean.append(value); seen.add(value.lower())
        with self.db._connect() as conn:
            conn.execute(
                f"UPDATE {self.USERS_TABLE} SET keywords = ?, updated_at = ? WHERE user_id = ?",
                (json.dumps(clean, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), user_id),
            )

    def get_enabled_platforms(self) -> list[str]:
        user_id = self._user_id_and_ensure()
        with self.db._connect() as conn:
            row = conn.execute(f"SELECT enabled_platforms FROM {self.USERS_TABLE} WHERE user_id = ?", (user_id,)).fetchone()
        if row is None or not row["enabled_platforms"]:
            return list(SUPPORTED_PLATFORMS)
        try:
            data = json.loads(row["enabled_platforms"])
            if isinstance(data, list):
                clean = [str(x).strip() for x in data if str(x).strip() in SUPPORTED_PLATFORMS]
                # Добавляем новые площадки в старые пользовательские настройки,
                # не меняя уже сделанный пользователем явный выбор остальных.
                known_before = {"eis", "b2b_center", "unipro", "rts_tender", "tmk"}
                if clean and set(clean).issubset(known_before) and "rosatom" not in clean:
                    clean.append("rosatom")
                    with self.db._connect() as write_conn:
                        write_conn.execute(
                            f"UPDATE {self.USERS_TABLE} SET enabled_platforms = ?, updated_at = ? WHERE user_id = ?",
                            (json.dumps(clean, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), user_id),
                        )
                return clean or list(SUPPORTED_PLATFORMS)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return list(SUPPORTED_PLATFORMS)

    def set_enabled_platforms(self, platforms: list[str]) -> None:
        user_id = self._user_id_and_ensure()
        clean = [x for x in dict.fromkeys(str(x).strip() for x in platforms) if x in SUPPORTED_PLATFORMS]
        with self.db._connect() as conn:
            conn.execute(
                f"UPDATE {self.USERS_TABLE} SET enabled_platforms = ?, updated_at = ? WHERE user_id = ?",
                (json.dumps(clean, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), user_id),
            )
