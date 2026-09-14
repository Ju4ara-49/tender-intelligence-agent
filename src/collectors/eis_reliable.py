"""EIS collector adapter that guarantees unified commercial-condition fields."""
from __future__ import annotations

from datetime import datetime

from src.collectors.base import CollectorUnavailableError
from src.collectors.eis_zakupki import EisZakupkiCollector, SEARCH_URL
from src.models.tender import Tender


class ReliableEisZakupkiCollector(EisZakupkiCollector):
    """EIS collector with a final commercial-terms enrichment pass."""

    def search(
        self,
        keywords: list[str],
        since: datetime | None = None,
    ) -> list[Tender]:
        """Fail closed when EIS is unreachable instead of returning false zero results."""
        clean_keywords = [str(value).strip() for value in keywords if str(value).strip()]
        if not clean_keywords:
            return []
        try:
            probe = self._get(
                SEARCH_URL,
                params={
                    "searchString": clean_keywords[0],
                    "morphology": "on",
                    "pageNumber": 1,
                    "recordsPerPage": f"_{min(self.records_per_page, 10)}",
                    "fz44": "on",
                    "fz223": "on",
                },
            )
        except Exception as exc:
            raise CollectorUnavailableError(
                f"eis: search endpoint unavailable: {type(exc).__name__}: {exc}"
            ) from exc
        if self._has_captcha(probe.text):
            raise CollectorUnavailableError("eis: search endpoint returned CAPTCHA/bot protection")
        return super().search(clean_keywords, since=since)

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
        # Commercial fields are mutated after Tender.__post_init__. Refresh the
        # persisted normalized snapshot so DB and notification fingerprints use
        # the same state as the final EIS detail result.
        tender._persist_normalized_fields()
        return tender
