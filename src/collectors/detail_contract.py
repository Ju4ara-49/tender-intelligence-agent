"""Shared post-processing for collector detail results."""
from __future__ import annotations

import re

from src.models.tender import Tender


_DETAIL_STATUSES = {"success", "partial", "failed"}
_INN_RE = re.compile(r"(?<!\d)(?:\d{10}|\d{12})(?!\d)")
_OKPD2_RE = re.compile(r"\b\d{2}(?:\.\d{1,3}){0,3}\b")
_PROCUREMENT_TYPES = {"commercial", "plan_schedule", "bankruptcy_property"}


def _normalize_inn(value: object) -> str:
    """Return only a valid Russian INN (10 or 12 digits)."""
    if value is None:
        return ""
    compact = re.sub(r"\s+", "", str(value)).strip()
    match = _INN_RE.search(compact)
    return match.group(0) if match else ""


def _extract_inn(tender: Tender) -> str:
    existing = _normalize_inn(tender.customer_inn)
    if existing:
        return existing

    raw = tender.raw_data if isinstance(tender.raw_data, dict) else {}
    for key in ("customer_inn", "inn", "customerInn", "customer_inn_number"):
        value = raw.get(key)
        normalized = _normalize_inn(value)
        if normalized:
            return normalized

    # Some collectors expose the customer/organizer as the only human-readable
    # source containing the INN. Include these fields in the common fallback so
    # platform adapters do not have to duplicate the same extraction logic.
    text_parts = [
        tender.customer,
        tender.description,
        str(raw.get("details", "")),
        str(raw.get("customer", "")),
        str(raw.get("organizer", "")),
    ]
    text = " ".join(text_parts)
    digit_pattern = r"(\d(?:\s*\d){9}(?:\s*\d\s*\d)?)"
    patterns = (
        rf"(?:ИНН|И\.Н\.Н\.)\s*[:№]?\s*{digit_pattern}\b",
        rf"\bИНН\s*{digit_pattern}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            normalized = _normalize_inn(match.group(1))
            if normalized:
                return normalized
    return ""


def _detail_text(tender: Tender) -> str:
    raw = tender.raw_data if isinstance(tender.raw_data, dict) else {}
    parts = [tender.title, tender.description]
    for key in ("details", "search_text", "document_text", "document_contents"):
        parts.append(str(raw.get(key) or ""))
    return " ".join(part for part in parts if part).strip()


def _extract_okpd2_codes(tender: Tender) -> list[str]:
    raw = tender.raw_data if isinstance(tender.raw_data, dict) else {}
    explicit = raw.get("okpd2_codes")
    if isinstance(explicit, (list, tuple, set)):
        values = [str(item).strip() for item in explicit if str(item).strip()]
        if values:
            return list(dict.fromkeys(values))

    text = _detail_text(tender)
    codes: list[str] = []
    marker = re.compile(r"(?:код\s+)?окпд\s*2?\s*[:№-]?\s*([^;|]{0,120})", re.I)
    for match in marker.finditer(text):
        segment = match.group(1)
        for code_match in _OKPD2_RE.finditer(segment):
            code = code_match.group(0)
            remainder = segment[code_match.end():].lstrip()
            if "." not in code and remainder and remainder[0].isdigit():
                continue
            if code not in codes:
                codes.append(code)
    return codes


def _classify_procurement_type(tender: Tender) -> str:
    raw = tender.raw_data if isinstance(tender.raw_data, dict) else {}
    explicit = str(raw.get("procurement_type") or tender.procurement_type or "").strip()
    if explicit in _PROCUREMENT_TYPES:
        return explicit

    text = _detail_text(tender).casefold().replace("ё", "е")
    if re.search(r"\bплан[\s-]+график\b", text):
        return "plan_schedule"
    if re.search(r"\bбанкрот\w*\b|\bреализац\w*\s+имуществ\w*\b|\bпродаж\w*\s+имуществ\w*\b", text):
        return "bankruptcy_property"
    if re.search(r"\bкоммерческ\w*\s+(?:закупк\w*|тендер\w*|торг\w*)\b", text):
        return "commercial"
    return ""


def enforce_detail_contract(collector) -> None:
    """Wrap one collector's get_details with the common STEP-25 contract.

    The wrapper does not replace platform parsers. It only normalizes their
    result after parsing and converts obvious WAF/skeleton results into explicit
    FAILED/PARTIAL states so the orchestrator can make a safe decision.
    """
    original = getattr(collector, "get_details", None)
    if not callable(original) or getattr(original, "_detail_contract_wrapped", False):
        return

    def wrapped(external_id: str):
        try:
            tender = original(external_id)
        except Exception:
            raise
        if tender is None:
            return None
        if not isinstance(tender, Tender):
            raise TypeError(f"{collector.platform}: get_details returned {type(tender).__name__}, expected Tender")

        tender.to_utc()
        if not tender.external_id:
            tender.external_id = str(external_id or "")

        raw = tender.raw_data if isinstance(tender.raw_data, dict) else {}
        tender.raw_data = raw

        if raw.get("waf_blocked") or raw.get("captcha") or raw.get("access_blocked"):
            tender.detail_status = "failed"
            tender.detail_diagnostics = str(
                raw.get("detail_diagnostics") or "Площадка вернула блокировку/WAF/CAPTCHA"
            )[:4000]
        else:
            if not tender.okpd2_codes:
                tender.okpd2_codes = _extract_okpd2_codes(tender)
            tender.procurement_type = _classify_procurement_type(tender)
            tender.customer_inn = _extract_inn(tender)
            missing = []
            if not str(tender.title or "").strip():
                missing.append("title")
            if not str(tender.url or "").strip():
                missing.append("url")
            if not str(tender.customer or "").strip():
                missing.append("customer")
            if tender.price is None:
                missing.append("price")
            if tender.deadline is None:
                missing.append("deadline")
            status = str(tender.detail_status or "success").lower()
            if status not in _DETAIL_STATUSES:
                status = "success"
            if missing and status == "success":
                status = "partial"
            tender.detail_status = status
            if missing:
                diagnostic = "Отсутствуют поля: " + ", ".join(missing)
                tender.detail_diagnostics = "; ".join(
                    item for item in (tender.detail_diagnostics, diagnostic) if item
                )[:4000]

        tender.raw_data["detail_status"] = tender.detail_status
        tender.raw_data["details_loaded"] = tender.detail_status != "failed"
        if tender.detail_diagnostics:
            tender.raw_data["detail_diagnostics"] = tender.detail_diagnostics
        tender.to_utc()
        return tender

    wrapped._detail_contract_wrapped = True
    collector.get_details = wrapped
