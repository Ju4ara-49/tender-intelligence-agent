"""Fabrikant V3: preserve V2 behavior and add reliable registry-region enrichment."""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from src.collectors.fabrikant_v2 import FabrikantV2Collector
from src.models.tender import Tender

logger = logging.getLogger(__name__)


class FabrikantV3Collector(FabrikantV2Collector):
    """Fabrikant V2 plus region extraction from the actual registry row.

    V2 already captures title, price, customer, publication date and deadline.
    Some Fabrikant registry layouts also expose a Region/Место поставки column,
    but V2 did not retain that column. This wrapper enriches the parsed Tender
    from the exact row values without changing the detail-loading behavior.
    """

    def _parse_results(self, html: str) -> list[Tender]:
        results = super()._parse_results(html)
        enriched = 0
        for tender in results:
            raw = tender.raw_data if isinstance(tender.raw_data, dict) else {}
            row = raw.get("search_row") if isinstance(raw.get("search_row"), dict) else {}
            headers = row.get("headers") or []
            values = row.get("values") or []
            region = self._value_by_header(headers, values, (
                "Регион",
                "Регион заказчика",
                "Регион поставки",
                "Место поставки",
                "Место нахождения",
                "Адрес поставки",
            ))
            if region and not tender.region:
                tender.region = region
                enriched += 1
            mapping = row.setdefault("mapping", {})
            mapping["region"] = self._header_index(headers, (
                "Регион",
                "Регион заказчика",
                "Регион поставки",
                "Место поставки",
                "Место нахождения",
                "Адрес поставки",
            ))
        if enriched:
            logger.info("fabrikant: region enriched from registry rows: %d", enriched)
        return results

    @classmethod
    def _header_index(cls, headers: list[str], names: tuple[str, ...]) -> int | None:
        normalized = [cls._norm(str(x)).lower().rstrip(":") for x in headers]
        for name in names:
            wanted = cls._norm(name).lower().rstrip(":")
            for idx, header in enumerate(normalized):
                if wanted == header or wanted in header or header in wanted:
                    return idx
        return None

    @classmethod
    def _value_by_header(cls, headers: list[str], values: list[str], names: tuple[str, ...]) -> str:
        idx = cls._header_index(headers, names)
        if idx is None or idx >= len(values):
            return ""
        value = cls._norm(str(values[idx]))
        if not value:
            return ""
        # Avoid propagating layout placeholders.
        if value.lower() in {"-", "—", "не указано", "не указан", "нет данных"}:
            return ""
        return value

    def get_details(self, external_id: str) -> Tender | None:
        detailed = super().get_details(external_id)
        if detailed and not detailed.region:
            detailed.region = self._extract_region_from_text(detailed.description or "")
            if detailed.region:
                raw = detailed.raw_data if isinstance(detailed.raw_data, dict) else {}
                raw["region_source"] = "detail_text"
                detailed.raw_data = raw
        return detailed

    @staticmethod
    def _extract_region_from_text(text: str) -> str:
        """Conservative fallback for obvious Russian federal-subject names."""
        text = re.sub(r"\s+", " ", text or "")
        patterns = (
            r"\b(?:Республика|респ\.)\s+[А-ЯЁ][А-ЯЁа-яё-]+(?:\s+[А-ЯЁа-яё-]+){0,2}",
            r"\b[А-ЯЁ][А-ЯЁа-яё-]+\s+(?:область|край|автономная область|автономный округ|АО)\b",
            r"\bг\.?\s*(?:Москва|Санкт-Петербург|Севастополь)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0).strip(" ,.;:")[:300]
        return ""
