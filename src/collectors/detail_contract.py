"""Shared post-processing for collector detail results."""
from __future__ import annotations

import re

from src.models.tender import Tender


_DETAIL_STATUSES = {"success", "partial", "failed"}
_INN_RE = re.compile(r"(?<!\d)(?:\d{10}|\d{12})(?!\d)")


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
