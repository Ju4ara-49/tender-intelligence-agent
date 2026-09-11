"""Рыночная аналитика поверх накопленной базы Tender Intelligence Agent.

Модуль намеренно не притворяется полноценной копией аналитики TenderPlan:
для прогноза побед, конкурентов, арбитража и фактических снижений цены нужны
исторические протоколы и внешние данные, которых текущие сборщики ещё не дают.
Зато уже сейчас можно строить полезную статистику по собственной базе.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.storage.database import TenderDatabase


@dataclass(frozen=True)
class MarketSnapshot:
    """Сводка по накопленной выборке тендеров."""

    total_tenders: int
    total_value: float
    average_price: float
    by_platform: list[dict[str, Any]]
    by_region: list[dict[str, Any]]
    by_customer: list[dict[str, Any]]
    by_law: list[dict[str, Any]]
    average_ai_score: float
    high_score_count: int


class MarketAnalytics:
    """Быстрая аналитика рынка без изменения существующей схемы SQLite."""

    def __init__(self, db: TenderDatabase) -> None:
        self.db = db

    @staticmethod
    def _rows(conn, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def snapshot(self, days: int | None = 30, min_ai_score: int = 0) -> MarketSnapshot:
        """Вернуть агрегаты за период.

        days=None означает всю историю. Период считается по first_seen_at.
        """
        where = []
        params: list[Any] = []
        if days is not None:
            since = datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))
            where.append("t.first_seen_at >= ?")
            params.append(since.isoformat())
        if min_ai_score > 0:
            where.append("COALESCE(a.relevance_score, 0) >= ?")
            params.append(int(min_ai_score))
        clause = " AND ".join(where) if where else "1=1"

        with self.db._connect() as conn:
            base = conn.execute(
                f"""
                SELECT COUNT(*) AS total,
                       COALESCE(SUM(t.price), 0) AS total_value,
                       COALESCE(AVG(t.price), 0) AS average_price,
                       COALESCE(AVG(a.relevance_score), 0) AS average_ai_score,
                       SUM(CASE WHEN COALESCE(a.relevance_score, 0) >= 80 THEN 1 ELSE 0 END) AS high_score_count
                FROM tenders t
                LEFT JOIN analyses a ON a.tender_id = t.id
                WHERE {clause}
                """,
                tuple(params),
            ).fetchone()

            def grouped(column: str, limit: int = 20) -> list[dict[str, Any]]:
                return self._rows(
                    conn,
                    f"""
                    SELECT COALESCE(NULLIF(TRIM(t.{column}), ''), 'Не указан') AS name,
                           COUNT(*) AS tenders,
                           COALESCE(SUM(t.price), 0) AS total_value,
                           COALESCE(AVG(t.price), 0) AS average_price,
                           COALESCE(AVG(a.relevance_score), 0) AS average_ai_score
                    FROM tenders t
                    LEFT JOIN analyses a ON a.tender_id = t.id
                    WHERE {clause}
                    GROUP BY name
                    ORDER BY tenders DESC, total_value DESC
                    LIMIT ?
                    """,
                    tuple(params) + (limit,),
                )

            return MarketSnapshot(
                total_tenders=int(base["total"] or 0),
                total_value=float(base["total_value"] or 0),
                average_price=float(base["average_price"] or 0),
                by_platform=grouped("platform"),
                by_region=grouped("region"),
                by_customer=grouped("customer"),
                by_law=grouped("law_type"),
                average_ai_score=float(base["average_ai_score"] or 0),
                high_score_count=int(base["high_score_count"] or 0),
            )
