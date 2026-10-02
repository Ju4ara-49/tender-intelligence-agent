from __future__ import annotations

import json
import math
import re
from contextvars import ContextVar
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


# Канонические режимы процедуры для контракта SearchProfile/SearchCriteria
# (docs/TENDERPLAN_SEARCH_RESEARCH_2026-09-19.md, блок «Тип закупки»).
# 44-ФЗ/223-ФЗ/615-ПП остаются в law_type — не смешиваем семантически разные
# фильтры. Применение на площадках — зона collectors (Kilo); контракт и
# persistence фиксируются здесь.
PROCUREMENT_TYPE_VALUES = ("commercial", "plan_schedule", "bankruptcy_property")

# ОКПД2: двухзначная группа плюс до трёх уточняющих групп, например
# "01", "01.11", "01.11.12", "01.11.12.110".
OKPD2_CODE_RE = re.compile(r"^\d{2}(?:\.\d{1,3}){0,3}$")


def normalize_okpd2_codes(value: list[str] | None) -> list[str]:
    """Каноническая нормализация кодов ОКПД2: strip, дедупликация, валидация."""
    if not value:
        return []
    result: list[str] = []
    for item in value:
        code = str(item).strip()
        if not code:
            continue
        if not OKPD2_CODE_RE.fullmatch(code):
            raise ValueError(f"Некорректный код ОКПД2: {code!r}")
        if code not in result:
            result.append(code)
    return result


def normalize_procurement_types(value: list[str] | None) -> list[str]:
    """Каноническая нормализация режимов процедуры (строго из white-list)."""
    if not value:
        return []
    result: list[str] = []
    for item in value:
        kind = str(item).strip()
        if not kind:
            continue
        if kind not in PROCUREMENT_TYPE_VALUES:
            raise ValueError(f"Неизвестный режим процедуры: {kind!r}")
        if kind not in result:
            result.append(kind)
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
    customer: str | None = None
    customer_inn: str | None = None
    law_type: str | None = None
    okpd2_codes: list[str] = field(default_factory=list)
    procurement_types: list[str] = field(default_factory=list)
    document_search: bool = False

    def __post_init__(self) -> None:
        """Reject contradictory numeric ranges before they reach the search pipeline."""
        for field_name in (
            "min_price", "max_price", "min_advance_percent",
            "min_application_security_percent", "max_application_security_percent",
            "min_contract_security_percent", "max_contract_security_percent",
        ):
            value = getattr(self, field_name)
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{field_name} должен быть конечным числом")
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
        if self.customer is not None:
            self.customer = str(self.customer).strip() or None
        if self.customer_inn is not None:
            self.customer_inn = str(self.customer_inn).strip() or None
        if self.law_type is not None:
            self.law_type = str(self.law_type).strip() or None
        self.okpd2_codes = normalize_okpd2_codes(self.okpd2_codes)
        self.procurement_types = normalize_procurement_types(self.procurement_types)


class CriteriaStore:
    """Хранение критериев Telegram отдельно для каждого пользователя."""

    USERS_TABLE = "tender_settings_users"
    DEFAULT_USER_ID = "default"

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db
        self._current_user_id: ContextVar[str] = ContextVar(
            f"criteria_store_user_{id(self)}", default=self.DEFAULT_USER_ID
        )
        self._ensure_schema()

    @classmethod
    def normalize_user_id(cls, user_id: str | int | None) -> str:
        value = str(user_id).strip() if user_id is not None else ""
        return value or cls.DEFAULT_USER_ID

    def set_user_id(self, user_id: str | int | None) -> None:
        """Set the explicit compatibility context used when user_id is omitted.

        Multi-user callers should continue passing user_id explicitly. This
        method exists for legacy single-user integrations and must never use
        stack inspection or hidden caller inference.
        """
        self._current_user_id.set(self.normalize_user_id(user_id))

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
                    customer TEXT,
                    customer_inn TEXT,
                    law_type TEXT,
                    okpd2_codes TEXT NOT NULL DEFAULT '[]',
                    procurement_types TEXT NOT NULL DEFAULT '[]',
                    document_search INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                 )
                 """
            )
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({self.USERS_TABLE})").fetchall()}
            for column, definition in (
                ("exclude_keywords", "TEXT NOT NULL DEFAULT '[]'"),
                ("regions", "TEXT NOT NULL DEFAULT '[]'"),
                ("okpd2_codes", "TEXT NOT NULL DEFAULT '[]'"),
                ("procurement_types", "TEXT NOT NULL DEFAULT '[]'"),
                ("document_search", "INTEGER NOT NULL DEFAULT 0"),
            ):
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
                            regions, enabled_platforms, customer, customer_inn, law_type,
                            okpd2_codes, procurement_types, document_search, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            self.DEFAULT_USER_ID, old_row["min_price"], old_row["max_price"], old_row["advance_required"],
                            old_row["min_advance_percent"], old_row["max_postpayment_days"], old_row["min_submission_days"],
                            old_row["min_application_security_percent"], old_row["max_application_security_percent"],
                            old_row["min_contract_security_percent"], old_row["max_contract_security_percent"],
                            old_row["min_ai_score"], old_row["keywords"], "[]", "[]",
                            json.dumps(SUPPORTED_PLATFORMS, ensure_ascii=False), None, None, None,
                            "[]", "[]", 0, old_row["updated_at"],
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
                        regions, enabled_platforms, customer, customer_inn, law_type,
                        okpd2_codes, procurement_types, document_search, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id, source["min_price"], source["max_price"], source["advance_required"], source["min_advance_percent"],
                        source["max_postpayment_days"], source["min_submission_days"], source["min_application_security_percent"],
                        source["max_application_security_percent"], source["min_contract_security_percent"],
                        source["max_contract_security_percent"], source["min_ai_score"], source["keywords"],
                        source["exclude_keywords"] if source["exclude_keywords"] is not None else "[]",
                        source["regions"] if source["regions"] is not None else "[]",
                        source["enabled_platforms"] if source["enabled_platforms"] is not None else json.dumps(SUPPORTED_PLATFORMS, ensure_ascii=False),
                        source["customer"] if source["customer"] is not None else None,
                        source["customer_inn"] if source["customer_inn"] is not None else None,
                        source["law_type"] if source["law_type"] is not None else None,
                        source["okpd2_codes"] if source["okpd2_codes"] is not None else "[]",
                        source["procurement_types"] if source["procurement_types"] is not None else "[]",
                        int(bool(source["document_search"])),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    def _user_id_and_ensure(self, user_id: str | int | None) -> str:
        normalized = self._current_user_id.get() if user_id is None else self.normalize_user_id(user_id)
        self._ensure_user(normalized)
        return normalized

    def _sync_default_profile(self, user_id: str, **values) -> None:
        """Keep legacy Telegram controls aligned with the canonical profile."""
        from src.profiles import SearchProfileStore

        store = SearchProfileStore(self.db)
        profiles = store.list(user_id)
        if not profiles:
            return
        profile = next((item for item in profiles if item.name == "Основной"), profiles[0])
        store.update(user_id, int(profile.id), **values)

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
            customer=row["customer"], customer_inn=row["customer_inn"], law_type=row["law_type"],
            okpd2_codes=normalize_okpd2_codes(self._loads(row["okpd2_codes"])),
            procurement_types=normalize_procurement_types(self._loads(row["procurement_types"])),
            document_search=bool(row["document_search"]),
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
        allowed = {"min_price", "max_price", "advance_required", "min_advance_percent", "max_postpayment_days", "min_submission_days", "min_application_security_percent", "max_application_security_percent", "min_contract_security_percent", "max_contract_security_percent", "min_ai_score", "customer", "customer_inn", "law_type", "okpd2_codes", "procurement_types", "document_search"}
        values = {key: value for key, value in values.items() if key in allowed}
        if not values:
            return
        user_id = self._user_id_and_ensure(user_id)
        current = self.get(user_id)
        candidate = {
            "min_price": current.min_price,
            "max_price": current.max_price,
            "advance_required": current.advance_required,
            "min_advance_percent": current.min_advance_percent,
            "max_postpayment_days": current.max_postpayment_days,
            "min_submission_days": current.min_submission_days,
            "min_application_security_percent": current.min_application_security_percent,
            "max_application_security_percent": current.max_application_security_percent,
            "min_contract_security_percent": current.min_contract_security_percent,
            "max_contract_security_percent": current.max_contract_security_percent,
            "min_ai_score": current.min_ai_score,
            "exclude_keywords": current.exclude_keywords,
            "regions": current.regions,
            "okpd2_codes": current.okpd2_codes,
            "procurement_types": current.procurement_types,
            "document_search": current.document_search,
        }
        candidate.update(values)
        TenderCriteria(**candidate)
        db_values = dict(values)
        if "okpd2_codes" in db_values:
            db_values["okpd2_codes"] = json.dumps(
                normalize_okpd2_codes(db_values["okpd2_codes"]),
                ensure_ascii=False,
            )
        if "procurement_types" in db_values:
            db_values["procurement_types"] = json.dumps(
                normalize_procurement_types(db_values["procurement_types"]),
                ensure_ascii=False,
            )
        if "document_search" in db_values:
            db_values["document_search"] = int(bool(db_values["document_search"]))
        db_values["updated_at"] = datetime.now(timezone.utc).isoformat()
        fields = ", ".join(f"{key} = ?" for key in db_values)
        with self.db._connect() as conn:
            conn.execute(f"UPDATE {self.USERS_TABLE} SET {fields} WHERE user_id = ?", (*db_values.values(), user_id))
        profile_values = {"exclusions" if key == "exclude_keywords" else key: value for key, value in values.items() if key != "updated_at"}
        if profile_values:
            self._sync_default_profile(user_id, **profile_values)

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
        self._sync_default_profile(user_id, keywords=_clean_list(keywords))

    def get_exclude_keywords(self, user_id: str | int | None = None) -> list[str]:
        user_id = self._user_id_and_ensure(user_id)
        with self.db._connect() as conn:
            row = conn.execute(f"SELECT exclude_keywords FROM {self.USERS_TABLE} WHERE user_id = ?", (user_id,)).fetchone()
        return self._loads(row["exclude_keywords"] if row else None)

    def set_exclude_keywords(self, user_id: str | int | None, keywords: list[str]) -> None:
        user_id = self._user_id_and_ensure(user_id)
        with self.db._connect() as conn:
            conn.execute(f"UPDATE {self.USERS_TABLE} SET exclude_keywords = ?, updated_at = ? WHERE user_id = ?", (json.dumps(_clean_list(keywords), ensure_ascii=False), datetime.now(timezone.utc).isoformat(), user_id))
        self._sync_default_profile(user_id, exclusions=_clean_list(keywords))

    def get_regions(self, user_id: str | int | None = None) -> list[str]:
        user_id = self._user_id_and_ensure(user_id)
        with self.db._connect() as conn:
            row = conn.execute(f"SELECT regions FROM {self.USERS_TABLE} WHERE user_id = ?", (user_id,)).fetchone()
        return self._loads(row["regions"] if row else None)

    def set_regions(self, user_id: str | int | None, regions: list[str]) -> None:
        user_id = self._user_id_and_ensure(user_id)
        with self.db._connect() as conn:
            conn.execute(f"UPDATE {self.USERS_TABLE} SET regions = ?, updated_at = ? WHERE user_id = ?", (json.dumps(_clean_list(regions), ensure_ascii=False), datetime.now(timezone.utc).isoformat(), user_id))
        self._sync_default_profile(user_id, regions=_clean_list(regions))

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
        self._sync_default_profile(user_id, platforms=clean)
