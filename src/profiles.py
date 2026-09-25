"""Сохранённые профили поиска ("Ключи") для Telegram-пользователей."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from src.storage.database import TenderDatabase
from src.telegram_settings import (
    CriteriaStore,
    TenderCriteria,
    normalize_okpd2_codes,
    normalize_procurement_types,
)


@dataclass
class SearchProfile:
    id: int | None = None
    user_id: str = ""
    name: str = "Основной"
    keywords: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
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
    customer: str | None = None
    customer_inn: str | None = None
    law_type: str | None = None
    # Контрактные фильтры (docs/TENDERPLAN_SEARCH_RESEARCH_2026-09-19.md):
    # сохраняются и валидируются, но площадками пока не применяются — зона
    # collectors (Kilo) подключит их позже. UI не выдаёт их за работающие.
    okpd2_codes: list[str] = field(default_factory=list)
    procurement_types: list[str] = field(default_factory=list)
    document_search: bool = False
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    def criteria(self) -> TenderCriteria:
        return TenderCriteria(
            min_price=self.min_price,
            max_price=self.max_price,
            advance_required=self.advance_required,
            min_advance_percent=self.min_advance_percent,
            max_postpayment_days=self.max_postpayment_days,
            min_submission_days=self.min_submission_days,
            min_application_security_percent=self.min_application_security_percent,
            max_application_security_percent=self.max_application_security_percent,
            min_contract_security_percent=self.min_contract_security_percent,
            max_contract_security_percent=self.max_contract_security_percent,
            min_ai_score=self.min_ai_score,
            exclude_keywords=list(self.exclusions),
            regions=list(self.regions),
            customer=self.customer,
            customer_inn=self.customer_inn,
            law_type=self.law_type,
            okpd2_codes=list(self.okpd2_codes),
            procurement_types=list(self.procurement_types),
            document_search=self.document_search,
        )


class SearchProfileStore:
    """SQLite CRUD для профилей поиска и фактической статистики их запусков."""

    PROFILES_TABLE = "search_profiles"
    RUNS_TABLE = "search_profile_runs"

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db
        self._ensure_schema()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json(value: list[str]) -> str:
        return json.dumps(value or [], ensure_ascii=False)

    @staticmethod
    def _loads(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            data = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return [str(item).strip() for item in data if str(item).strip()] if isinstance(data, list) else []

    def _ensure_schema(self) -> None:
        with self.db._connect() as conn:
            conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self.PROFILES_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    keywords TEXT NOT NULL DEFAULT '[]',
                    exclusions TEXT NOT NULL DEFAULT '[]',
                    platforms TEXT NOT NULL DEFAULT '[]',
                    regions TEXT NOT NULL DEFAULT '[]',
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
                    customer TEXT,
                    customer_inn TEXT,
                    law_type TEXT,
                    okpd2_codes TEXT NOT NULL DEFAULT '[]',
                    procurement_types TEXT NOT NULL DEFAULT '[]',
                    document_search INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, name)
                );

                CREATE TABLE IF NOT EXISTS {self.RUNS_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER NOT NULL,
                    search_number INTEGER,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    found INTEGER NOT NULL DEFAULT 0,
                    filtered INTEGER NOT NULL DEFAULT 0,
                    new_count INTEGER NOT NULL DEFAULT 0,
                    analyzed INTEGER NOT NULL DEFAULT 0,
                    notified INTEGER NOT NULL DEFAULT 0,
                    duplicates INTEGER NOT NULL DEFAULT 0,
                    excluded_by_criteria INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(profile_id) REFERENCES {self.PROFILES_TABLE}(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_search_profiles_user ON {self.PROFILES_TABLE}(user_id);
                CREATE INDEX IF NOT EXISTS idx_search_profile_runs_profile ON {self.RUNS_TABLE}(profile_id, finished_at);
                """
            )

            # Existing installations may have these tables from the pre-profile
            # schema. CREATE TABLE IF NOT EXISTS does not add new columns, so
            # migrate every field used by the current dataclasses explicitly.
            profile_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({self.PROFILES_TABLE})").fetchall()}
            profile_migrations = {
                "keywords": "TEXT NOT NULL DEFAULT '[]'",
                "exclusions": "TEXT NOT NULL DEFAULT '[]'",
                "platforms": "TEXT NOT NULL DEFAULT '[]'",
                "regions": "TEXT NOT NULL DEFAULT '[]'",
                "min_price": "REAL",
                "max_price": "REAL",
                "advance_required": "INTEGER NOT NULL DEFAULT 0",
                "min_advance_percent": "REAL NOT NULL DEFAULT 0",
                "max_postpayment_days": "INTEGER",
                "min_submission_days": "INTEGER NOT NULL DEFAULT 7",
                "min_application_security_percent": "REAL NOT NULL DEFAULT 0",
                "max_application_security_percent": "REAL",
                "min_contract_security_percent": "REAL NOT NULL DEFAULT 0",
                "max_contract_security_percent": "REAL",
                "min_ai_score": "INTEGER NOT NULL DEFAULT 70",
                "customer": "TEXT",
                "customer_inn": "TEXT",
                "law_type": "TEXT",
                "okpd2_codes": "TEXT NOT NULL DEFAULT '[]'",
                "procurement_types": "TEXT NOT NULL DEFAULT '[]'",
                "document_search": "INTEGER NOT NULL DEFAULT 0",
                "enabled": "INTEGER NOT NULL DEFAULT 1",
                "created_at": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in profile_migrations.items():
                if column not in profile_columns:
                    conn.execute(f"ALTER TABLE {self.PROFILES_TABLE} ADD COLUMN {column} {definition}")

            run_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({self.RUNS_TABLE})").fetchall()}
            run_migrations = {
                "search_number": "INTEGER",
                "found": "INTEGER NOT NULL DEFAULT 0",
                "filtered": "INTEGER NOT NULL DEFAULT 0",
                "new_count": "INTEGER NOT NULL DEFAULT 0",
                "analyzed": "INTEGER NOT NULL DEFAULT 0",
                "notified": "INTEGER NOT NULL DEFAULT 0",
                "duplicates": "INTEGER NOT NULL DEFAULT 0",
                "excluded_by_criteria": "INTEGER NOT NULL DEFAULT 0",
            }
            for column, definition in run_migrations.items():
                if column not in run_columns:
                    conn.execute(f"ALTER TABLE {self.RUNS_TABLE} ADD COLUMN {column} {definition}")

    @classmethod
    def _from_row(cls, row) -> SearchProfile:
        return SearchProfile(
            id=int(row["id"]), user_id=row["user_id"], name=row["name"],
            keywords=cls._loads(row["keywords"]), exclusions=cls._loads(row["exclusions"]),
            platforms=cls._loads(row["platforms"]), regions=cls._loads(row["regions"]),
            min_price=row["min_price"], max_price=row["max_price"],
            advance_required=bool(row["advance_required"]), min_advance_percent=float(row["min_advance_percent"]),
            max_postpayment_days=row["max_postpayment_days"], min_submission_days=int(row["min_submission_days"]),
            min_application_security_percent=float(row["min_application_security_percent"]),
            max_application_security_percent=row["max_application_security_percent"],
            min_contract_security_percent=float(row["min_contract_security_percent"]),
            max_contract_security_percent=row["max_contract_security_percent"], min_ai_score=int(row["min_ai_score"]),
            customer=row["customer"], customer_inn=row["customer_inn"], law_type=row["law_type"],
            okpd2_codes=cls._loads(row["okpd2_codes"]), procurement_types=cls._loads(row["procurement_types"]),
            document_search=bool(row["document_search"]),
            enabled=bool(row["enabled"]), created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _validate_values(profile: SearchProfile) -> None:
        """Reject impossible ranges before persistence."""
        ranges = (
            ("min_price", profile.min_price, "max_price", profile.max_price),
            ("min_application_security_percent", profile.min_application_security_percent, "max_application_security_percent", profile.max_application_security_percent),
            ("min_contract_security_percent", profile.min_contract_security_percent, "max_contract_security_percent", profile.max_contract_security_percent),
        )
        for min_name, minimum, max_name, maximum in ranges:
            for name, value in ((min_name, minimum), (max_name, maximum)):
                if value is None:
                    continue
                number = float(value)
                if not math.isfinite(number) or number < 0:
                    raise ValueError(f"{name} должен быть неотрицательным конечным числом")
            if minimum is not None and maximum is not None and float(minimum) > float(maximum):
                raise ValueError(f"{min_name} не может быть больше {max_name}")
        if not 0 <= float(profile.min_advance_percent) <= 100:
            raise ValueError("min_advance_percent должен быть от 0 до 100")
        if profile.max_postpayment_days is not None and profile.max_postpayment_days < 0:
            raise ValueError("max_postpayment_days должен быть неотрицательным")
        if profile.min_submission_days < 0:
            raise ValueError("min_submission_days должен быть неотрицательным")
        if not 0 <= profile.min_ai_score <= 100:
            raise ValueError("min_ai_score должен быть от 0 до 100")
        # Каноническая нормализация контрактных фильтров (валидация формата
        # ОКПД2 и white-list режимов процедуры выполняется в telegram_settings).
        profile.okpd2_codes = normalize_okpd2_codes(profile.okpd2_codes)
        profile.procurement_types = normalize_procurement_types(profile.procurement_types)

    def create(self, user_id: str | int, profile: SearchProfile | None = None, **values) -> SearchProfile:
        user_id = str(user_id).strip()
        if not user_id:
            raise ValueError("user_id обязателен")
        if profile is None:
            profile = SearchProfile(user_id=user_id, **values)
        else:
            profile.user_id = user_id
            for key, value in values.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)
        self._validate_values(profile)
        now = self._now()
        profile.created_at = profile.created_at or now
        profile.updated_at = now
        fields = (
            "user_id", "name", "keywords", "exclusions", "platforms", "regions", "min_price", "max_price",
            "advance_required", "min_advance_percent", "max_postpayment_days", "min_submission_days",
            "min_application_security_percent", "max_application_security_percent", "min_contract_security_percent",
            "max_contract_security_percent", "min_ai_score", "customer", "customer_inn", "law_type",
            "okpd2_codes", "procurement_types", "document_search", "enabled", "created_at", "updated_at",
        )
        values_tuple = (
            profile.user_id, profile.name.strip(), self._json(profile.keywords), self._json(profile.exclusions),
            self._json(profile.platforms), self._json(profile.regions), profile.min_price, profile.max_price,
            int(profile.advance_required), profile.min_advance_percent, profile.max_postpayment_days,
            profile.min_submission_days, profile.min_application_security_percent, profile.max_application_security_percent,
            profile.min_contract_security_percent, profile.max_contract_security_percent, profile.min_ai_score,
            profile.customer, profile.customer_inn, profile.law_type,
            self._json(profile.okpd2_codes), self._json(profile.procurement_types),
            int(profile.document_search), int(profile.enabled), profile.created_at, profile.updated_at,
        )
        with self.db._connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO {self.PROFILES_TABLE} ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                values_tuple,
            )
            profile.id = int(cursor.lastrowid)
        return profile

    def list(self, user_id: str | int, enabled_only: bool = False) -> list[SearchProfile]:
        user_id = str(user_id).strip()
        query = f"SELECT * FROM {self.PROFILES_TABLE} WHERE user_id = ?"
        params: list[object] = [user_id]
        if enabled_only:
            query += " AND enabled = 1"
        query += " ORDER BY enabled DESC, name COLLATE NOCASE ASC, id ASC"
        with self.db._connect() as conn:
            return [self._from_row(row) for row in conn.execute(query, params).fetchall()]

    def get(self, user_id: str | int, profile_id: int) -> SearchProfile | None:
        with self.db._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {self.PROFILES_TABLE} WHERE id = ? AND user_id = ?", (profile_id, str(user_id).strip())
            ).fetchone()
        return self._from_row(row) if row else None

    def update(self, user_id: str | int, profile_id: int, **values) -> SearchProfile:
        allowed = {field.name for field in SearchProfile.__dataclass_fields__.values()} - {"id", "user_id", "created_at", "updated_at"}
        values = {key: value for key, value in values.items() if key in allowed}
        if not values:
            result = self.get(user_id, profile_id)
            if result is None:
                raise KeyError(profile_id)
            return result
        if "name" in values:
            values["name"] = str(values["name"]).strip()
        for key in {"keywords", "exclusions", "platforms", "regions"} & values.keys():
            values[key] = self._json(values[key])
        # Контрактные фильтры: в SQL уходит JSON, а в candidate для валидации —
        # нормализованные списки (не закодированные строки).
        normalized_contract: dict[str, list[str]] = {}
        if "okpd2_codes" in values:
            normalized_contract["okpd2_codes"] = normalize_okpd2_codes(values["okpd2_codes"])
            values["okpd2_codes"] = self._json(normalized_contract["okpd2_codes"])
        if "procurement_types" in values:
            normalized_contract["procurement_types"] = normalize_procurement_types(values["procurement_types"])
            values["procurement_types"] = self._json(normalized_contract["procurement_types"])
        for key in {"advance_required", "enabled"} & values.keys():
            values[key] = int(bool(values[key]))

        candidate = self.get(user_id, profile_id)
        if candidate is None:
            raise KeyError(profile_id)
        for key, value in values.items():
            if hasattr(candidate, key):
                setattr(candidate, key, normalized_contract.get(key, value))
        self._validate_values(candidate)
        values.pop("updated_at", None)
        values["updated_at"] = self._now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self.db._connect() as conn:
            cursor = conn.execute(
                f"UPDATE {self.PROFILES_TABLE} SET {assignments} WHERE id = ? AND user_id = ?",
                (*values.values(), profile_id, str(user_id).strip()),
            )
            if cursor.rowcount != 1:
                raise KeyError(profile_id)
        result = self.get(user_id, profile_id)
        if result is None:
            raise KeyError(profile_id)
        return result

    def delete(self, user_id: str | int, profile_id: int) -> None:
        with self.db._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM {self.PROFILES_TABLE} WHERE id = ? AND user_id = ?", (profile_id, str(user_id).strip())
            )
            if cursor.rowcount != 1:
                raise KeyError(profile_id)

    def set_enabled(self, user_id: str | int, profile_id: int, enabled: bool) -> SearchProfile:
        return self.update(user_id, profile_id, enabled=enabled)

    def duplicate(self, user_id: str | int, profile_id: int, name: str) -> SearchProfile:
        source = self.get(user_id, profile_id)
        if source is None:
            raise KeyError(profile_id)
        data = asdict(source)
        data.pop("id", None)
        data.pop("created_at", None)
        data.pop("updated_at", None)
        data["name"] = name
        return self.create(user_id, SearchProfile(**data))

    def ensure_default_profile(self, user_id: str | int, criteria_store: CriteriaStore) -> SearchProfile:
        user_id = str(user_id).strip()
        existing = self.list(user_id)
        if existing:
            return existing[0]
        criteria = criteria_store.get(user_id)
        return self.create(
            user_id,
            SearchProfile(
                user_id=user_id,
                name="Основной",
                keywords=criteria_store.get_keywords(user_id) or [],
                exclusions=list(criteria.exclude_keywords),
                platforms=criteria_store.get_enabled_platforms(user_id),
                regions=list(criteria.regions),
                min_price=criteria.min_price,
                max_price=criteria.max_price,
                advance_required=criteria.advance_required,
                min_advance_percent=criteria.min_advance_percent,
                max_postpayment_days=criteria.max_postpayment_days,
                min_submission_days=criteria.min_submission_days,
                min_application_security_percent=criteria.min_application_security_percent,
                max_application_security_percent=criteria.max_application_security_percent,
                min_contract_security_percent=criteria.min_contract_security_percent,
                max_contract_security_percent=criteria.max_contract_security_percent,
                min_ai_score=criteria.min_ai_score,
                customer=criteria.customer,
                customer_inn=criteria.customer_inn,
                law_type=criteria.law_type,
                okpd2_codes=list(criteria.okpd2_codes),
                procurement_types=list(criteria.procurement_types),
                document_search=bool(criteria.document_search),
            ),
        )

    def record_run(self, user_id: str | int, profile_id: int, stats: dict[str, int], started_at: str | None = None) -> None:
        if self.get(user_id, profile_id) is None:
            raise KeyError(profile_id)
        finished_at = self._now()
        started_at = started_at or finished_at
        with self.db._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self.RUNS_TABLE} (
                    profile_id, search_number, started_at, finished_at, found, filtered, new_count,
                    analyzed, notified, duplicates, excluded_by_criteria
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id, stats.get("search_number"), started_at, finished_at,
                    stats.get("found", 0), stats.get("filtered", 0), stats.get("new", 0),
                    stats.get("analyzed", 0), stats.get("notified", 0), stats.get("skipped_duplicate", 0),
                    stats.get("excluded_by_criteria", 0),
                ),
            )

    def stats(self, user_id: str | int, profile_id: int) -> dict[str, int | None]:
        if self.get(user_id, profile_id) is None:
            raise KeyError(profile_id)
        with self.db._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS runs, COALESCE(SUM(found), 0) AS found,
                       COALESCE(SUM(filtered), 0) AS filtered, COALESCE(SUM(new_count), 0) AS new_count,
                       COALESCE(SUM(analyzed), 0) AS analyzed, COALESCE(SUM(notified), 0) AS notified,
                       COALESCE(SUM(duplicates), 0) AS duplicates,
                       COALESCE(SUM(excluded_by_criteria), 0) AS excluded_by_criteria,
                       MAX(finished_at) AS last_run_at
                FROM {self.RUNS_TABLE} WHERE profile_id = ?
                """,
                (profile_id,),
            ).fetchone()
        return {key: row[key] for key in row.keys()}
