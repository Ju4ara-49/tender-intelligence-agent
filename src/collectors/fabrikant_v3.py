"""Fabrikant V3: robust metadata enrichment for public procedures."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from src.collectors.fabrikant_v2 import FabrikantV2Collector
from src.models.tender import Tender

logger = logging.getLogger(__name__)


class FabrikantV3Collector(FabrikantV2Collector):
    """Fabrikant V2 plus reliable common-field enrichment."""

    def _parse_results(self, html: str) -> list[Tender]:
        results = super()._parse_results(html)
        enriched = 0
        for tender in results:
            raw = tender.raw_data if isinstance(tender.raw_data, dict) else {}
            row = raw.get("search_row") if isinstance(raw.get("search_row"), dict) else {}
            headers = row.get("headers") or []
            values = row.get("values") or []
            names = (
                "Регион", "Регион заказчика", "Регион поставки", "Место поставки",
                "Место нахождения", "Адрес поставки",
            )
            region = self._value_by_header(headers, values, names)
            if region and not tender.region:
                tender.region = region
                enriched += 1
            mapping = row.setdefault("mapping", {})
            mapping["region"] = self._header_index(headers, names)
            raw["search_row"] = row
            tender.raw_data = raw
        if enriched:
            logger.info("fabrikant: region enriched from registry rows: %d", enriched)
        return results

    @staticmethod
    def _procedure_anchor(row, base_host):
        """Resolve procedure links against the active Fabrikant host.

        Fabrikant uses separate `soap2` and `soap4` hosts for 223-FZ and
        44-FZ. The V2 parser previously hard-coded `soap4` when resolving a
        relative href, which caused relative 223-FZ procedure links to be
        rejected before the rich registry-row parser could run. Keep the
        active host supplied by V2 so both registries retain their table
        metadata (customer, price, dates, etc.).
        """
        base_url = f"https://{base_host}/"
        for anchor in row.find_all("a", href=True):
            href = str(anchor.get("href", "")).strip()
            if not href:
                continue
            full = urljoin(base_url, href)
            if urlparse(full).netloc.lower() == base_host.lower() and "/procedure/" in full.lower():
                return anchor
        return None

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
        if value.lower() in {"-", "—", "не указано", "не указан", "нет данных"}:
            return ""
        return value

    def get_details(self, external_id: str) -> Tender | None:
        detailed = super().get_details(external_id)
        if not detailed:
            return None
        text = detailed.description or ""
        if not detailed.published_at:
            published = self._extract_publication_date(text)
            if published:
                detailed.published_at = published
                detailed.start_date = published
                raw = detailed.raw_data if isinstance(detailed.raw_data, dict) else {}
                raw["published_at_source"] = "detail_text"
                detailed.raw_data = raw
                # __post_init__'s UTC normalization already ran at
                # construction time and does not re-fire on attribute
                # assignment, so a naive Moscow-local datetime set here
                # would otherwise stay naive/un-normalized on the Tender
                # instance. Explicitly re-normalize after the assignment.
                detailed.to_utc()
        if not detailed.region:
            region = self._extract_region_from_text(text)
            if region:
                detailed.region = region
                raw = detailed.raw_data if isinstance(detailed.raw_data, dict) else {}
                raw["region_source"] = "detail_text"
                detailed.raw_data = raw

        # Common commercial terms are often present in the procedure text but
        # were previously discarded. Fill the unified Tender fields so Telegram
        # criteria can operate consistently with the browser collector.
        if detailed.advance_percent is None:
            detailed.advance_percent = self._extract_percent(
                text, ("Аванс", "Предоплата", "Размер аванса", "Авансовый платеж")
            )
        if detailed.advance_percent is not None:
            detailed.advance_required = detailed.advance_percent > 0
        if detailed.postpayment_days is None:
            detailed.postpayment_days = self._extract_days(
                text, ("Отсрочка платежа", "Срок оплаты", "Условия оплаты", "Постоплата")
            )
        if detailed.application_security_percent is None:
            detailed.application_security_percent = self._extract_percent(
                text, ("Обеспечение заявки", "Обеспечение предложения")
            )
        if detailed.contract_security_percent is None:
            detailed.contract_security_percent = self._extract_percent(
                text, ("Обеспечение исполнения", "Обеспечение контракта", "Обеспечение договора")
            )

        raw = detailed.raw_data if isinstance(detailed.raw_data, dict) else {}
        if detailed.advance_percent is not None:
            raw["advance_payment"] = {"percent": detailed.advance_percent}
        if detailed.postpayment_days is not None:
            raw["postpayment"] = {"days": detailed.postpayment_days}
        if detailed.application_security_percent is not None:
            raw["application_security"] = {"percent": detailed.application_security_percent}
        if detailed.contract_security_percent is not None:
            raw["contract_security"] = {"percent": detailed.contract_security_percent}
        detailed.raw_data = raw
        return detailed

    @classmethod
    def _extract_publication_date(cls, text: str) -> datetime | None:
        """Prefer explicit publication date; otherwise use application start date."""
        normalized = cls._norm(text)
        month = r"января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря"
        patterns = (
            rf"(?:дата публикации|дата размещения|опубликовано|размещено)\D{{0,80}}(\d{{1,2}}\s+(?:{month})\s+20\d{{2}}(?:\s+\d{{1,2}}:\d{{2}})?)",
            r"(?:дата публикации|дата размещения|опубликовано|размещено)\D{0,80}(\d{1,2}[./-]\d{1,2}[./-]20\d{2}(?:\s+\d{1,2}:\d{2})?)",
            rf"(\d{{1,2}}\s+(?:{month})\s+20\d{{2}}(?:\s+\d{{1,2}}:\d{{2}})?)\s*[•|-]?\s*начало(?: приема| подачи)?",
            r"(\d{1,2}[./-]\d{1,2}[./-]20\d{2}(?:\s+\d{1,2}:\d{2})?)\s*[•|-]?\s*начало(?: приема|подачи)?",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized, re.I)
            if match:
                parsed = cls._parse_human_date(match.group(1))
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _parse_human_date(value: str) -> datetime | None:
        value = re.sub(r"\s+", " ", value.strip())
        months = {
            "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
            "мая": 5, "июня": 6, "июля": 7, "августа": 8,
            "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
        }
        match = re.fullmatch(r"(\d{1,2})\s+([А-Яа-яЁё]+)\s+(20\d{2})(?:\s+(\d{1,2}):(\d{2}))?", value)
        if match and match.group(2).lower() in months:
            try:
                hour = int(match.group(4)) if match.group(4) is not None else 12
                minute = int(match.group(5)) if match.group(5) is not None else 0
                return datetime(int(match.group(3)), months[match.group(2).lower()], int(match.group(1)), hour, minute)
            except ValueError:
                return None
        match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?:\s+(\d{1,2}):(\d{2}))?", value)
        if match:
            try:
                hour = int(match.group(4)) if match.group(4) is not None else 12
                minute = int(match.group(5)) if match.group(5) is not None else 0
                return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)), hour, minute)
            except ValueError:
                return None
        return None

    @staticmethod
    def _extract_region_from_text(text: str) -> str:
        text = re.sub(r"\s+", " ", text or "")
        patterns = (
            r"\bРеспублика\s+[А-ЯЁ][А-ЯЁа-яё-]+(?:\s+[А-ЯЁа-яё-]+){0,2}",
            r"\b[А-ЯЁ][А-ЯЁа-яё-]+(?:\s+[А-ЯЁа-яё-]+){0,2}\s+Респ(?:ублика)?\b",
            r"\b[А-ЯЁ][А-ЯЁа-яё-]+(?:\s+[А-ЯЁа-яё-]+){0,2}\s+(?:область|край|автономная область|автономный округ)\b",
            r"\bг\.?\s*(?:Москва|Санкт-Петербург|Севастополь)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(0).strip(" ,.;:")[:300]
        return ""
