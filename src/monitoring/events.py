"""Детерминированные типы событий мониторинга тендера."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

@dataclass(frozen=True)
class TenderEvent:
    event_type: str
    tender_id: int
    unique_key: str
    categories: tuple[str, ...]
    fingerprint: str

def make_event_fingerprint(
    unique_key: str,
    event_type: str,
    snapshot: Mapping[str, Any],
    categories: tuple[str, ...] = (),
) -> str:
    payload = {
        "unique_key": str(unique_key),
        "event_type": str(event_type),
        "categories": list(categories),
        "snapshot": snapshot,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def build_change_event(
    tender_id: int,
    unique_key: str,
    snapshot: Mapping[str, Any],
    categories: tuple[str, ...],
) -> TenderEvent:
    return TenderEvent(
        event_type="tender_changed",
        tender_id=int(tender_id),
        unique_key=str(unique_key),
        categories=tuple(categories),
        fingerprint=make_event_fingerprint(unique_key, "tender_changed", snapshot, categories),
    )
