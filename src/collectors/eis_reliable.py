"""EIS collector adapter that guarantees unified commercial-condition fields."""
from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.collectors.base import CollectorUnavailableError
from src.collectors.eis_zakupki import BASE_URL, EisZakupkiCollector, SEARCH_URL
from src.models.tender import Tender
from src.collectors.tenderguru_fallback import search as tenderguru_search


class ReliableEisZakupkiCollector(EisZakupkiCollector):
    """EIS collector with a final commercial-terms enrichment pass."""

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        # The public-index fallback is a degraded mode and therefore opt-in: by
        # default an unreachable EIS must fail closed instead of looking like a
        # healthy search that legitimately found nothing.
        self.allow_public_fallback = bool(self.config.get("allow_public_fallback", False))

    def search(
        self,
        keywords: list[str],
        since: datetime | None = None,
    ) -> list[Tender]:
        """Fail closed when EIS is unreachable instead of returning false zero results."""
        clean_keywords = [str(value).strip() for value in keywords if str(value).strip()]
        if not clean_keywords:
            return []
        rss_results: list[Tender] = []
        rss_errors: list[Exception] = []
        for keyword in clean_keywords:
            try:
                rss_results.extend(self._search_rss(keyword, since))
            except Exception as exc:
                rss_errors.append(exc)
                continue
        if rss_results:
            unique: dict[str, Tender] = {item.unique_key: item for item in rss_results}
            return list(unique.values())

        # GitHub-hosted runners can be unable to route to zakupki.gov.ru. The
        # public indexed fallback is explicitly opt-in (`allow_public_fallback`)
        # and never bypasses EIS authentication or WAF controls. Because it is a
        # degraded source, using it must stay visible through `_last_search_error`
        # instead of masquerading as a healthy first-party EIS search.
        primary_unavailable = bool(rss_errors) and len(rss_errors) == len(clean_keywords)
        if self.allow_public_fallback:
            fallback = self._public_fallback(clean_keywords)
            if fallback:
                if primary_unavailable:
                    self._last_search_error = (
                        "eis: degraded public fallback used; primary search unavailable: "
                        f"{type(rss_errors[-1]).__name__}: {rss_errors[-1]}"
                    )
                return fallback
        if primary_unavailable:
            raise self._unavailable_error(rss_errors[-1]) from rss_errors[-1]

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
            detail = rss_errors[-1] if rss_errors else exc
            raise self._unavailable_error(detail) from detail
        if self._has_captcha(probe.text):
            raise CollectorUnavailableError("eis: search endpoint returned CAPTCHA/bot protection")
        return super().search(clean_keywords, since=since)

    @staticmethod
    def _unavailable_error(detail: Exception) -> CollectorUnavailableError:
        return CollectorUnavailableError(
            f"eis: search endpoint unavailable: {type(detail).__name__}: {detail}"
        )

    def _public_fallback(self, keywords: list[str]) -> list[Tender]:
        """Best-effort public index; every item is marked as a degraded source."""
        results: dict[str, Tender] = {}
        for keyword in keywords:
            try:
                found = tenderguru_search(
                    platform=self.platform,
                    keyword=keyword,
                    timeout=min(max(self.timeout, 5), 20),
                    max_results=self.records_per_page * self.max_pages,
                )
            except Exception:
                continue
            for tender in found:
                tender.raw_data["degraded"] = True
                tender.raw_data["degraded_source"] = "tenderguru_public_fallback"
                results[tender.unique_key] = tender
        return list(results.values())

    def _search_rss(self, keyword: str, since: datetime | None) -> list[Tender]:
        """Use EIS's lightweight public RSS search instead of the heavy HTML registry.
        The RSS endpoint is a first-class public search surface and is much less
        sensitive to the 2026 registry SPA/HTML changes.
        """
        url = SEARCH_URL.replace("/results.html", "/rss.html")
        response = self._get(
            url,
            params={
                "searchString": keyword,
                "morphology": "on",
                "pageNumber": 1,
                "recordsPerPage": f"_{max(50, self.records_per_page * self.max_pages)}",
                "fz44": "on",
                "fz223": "on",
                "sortDirection": "false",
                "sortBy": "UPDATE_DATE",
            },
        )
        if self._has_captcha(response.text):
            raise CollectorUnavailableError("eis: RSS endpoint returned CAPTCHA/bot protection")
        soup = BeautifulSoup(response.text, "xml")
        items = soup.find_all("item")
        results: list[Tender] = []
        for item in items:
            title_node = item.find("title")
            title = self._clean_text(title_node.get_text(" ", strip=True) if title_node else "")
            link_node = item.find("link")
            link = self._clean_text(link_node.get_text(" ", strip=True) if link_node else "")
            guid_node = item.find("guid")
            guid = self._clean_text(guid_node.get_text(" ", strip=True) if guid_node else "")
            description_node = item.find("description")
            description = self._clean_text(
                BeautifulSoup(
                    description_node.get_text(" ", strip=True) if description_node else "",
                    "html.parser",
                ).get_text(" ", strip=True)
            )
            external_id = self._extract_reg_number(link, f"{title} {guid} {description}")
            if not external_id or not title:
                continue
            published = None
            date_node = item.find("pubDate")
            if date_node:
                try:
                    published = parsedate_to_datetime(date_node.get_text(" ", strip=True))
                except (TypeError, ValueError, OverflowError):
                    published = None
            if since is not None and published is not None:
                if published.tzinfo is None:
                    published = published.replace(tzinfo=since.tzinfo)
                if published < since:
                    continue
            results.append(
                Tender(
                    platform=self.platform,
                    external_id=external_id,
                    title=title[:1000],
                    url=urljoin(BASE_URL, link),
                    description=description[:10000] or title[:10000],
                    published_at=published,
                    raw_data={"keyword": keyword, "source": "eis_rss", "guid": guid},
                )
            )
        return results

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
