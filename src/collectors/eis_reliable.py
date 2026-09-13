"""EIS collector adapter that guarantees unified commercial-condition fields."""
from __future__ import annotations

from src.collectors.eis_zakupki import EisZakupkiCollector
from src.models.tender import Tender


class ReliableEisZakupkiCollector(EisZakupkiCollector):
    """EIS collector with a final commercial-terms enrichment pass."""

    def get_details(self, external_id: str) -> Tender | None:
        tender = super().get_details(external_id)
        if tender is None:
            return None

        text = " ".join(
            part for part in (
                tender.description,
                str(tender.raw_data.get("details", "")),
                str(tender.raw_data.get("search_text", "")),
            ) if part
        )
        conditions = self._extract_commercial_conditions(text)
        if conditions.get("advance_percent") is not None:
            tender.advance_percent = float(conditions["advance_percent"])
            tender.advance_required = True
        elif conditions.get("advance_required"):
            tender.advance_required = True
        if conditions.get("postpayment_days") is not None:
            tender.postpayment_days = int(conditions["postpayment_days"])
        if conditions.get("application_security_percent") is not None:
            tender.application_security_percent = float(conditions["application_security_percent"])
        if conditions.get("contract_security_percent") is not None:
            tender.contract_security_percent = float(conditions["contract_security_percent"])

        tender.raw_data["commercial_conditions"] = conditions
        # The base Tender persists _normalized during construction, but this
        # adapter mutates commercial fields afterwards. Refresh it so SQLite
        # event fingerprints and recipient delivery fingerprints see the same
        # state and do not diverge after an EIS detail enrichment.
        tender._persist_normalized_fields()
        return tender
