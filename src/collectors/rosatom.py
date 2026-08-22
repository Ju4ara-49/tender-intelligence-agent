"""Collector for the public Rosatom procurement portal.

The Rosatom portal is a legacy/JS-heavy public site. The collector uses
Playwright and the portal's published procurements page. It does not bypass
WAF, CAPTCHA, authentication, or other access controls.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from src.collectors.browser_public import _BrowserTenderCollector
from src.models.tender import Tender

logger = logging.getLogger(__name__)


class RosatomCollector(_BrowserTenderCollector):
    """Public procurement search on zakupki.rosatom.ru."""

    platform = "rosatom"
    BASE_URL = "https://zakupki.rosatom.ru/?link=published_procurements"
    SEARCH_HINTS = (
        "Поиск",
        "Найти",
        "Искать",
        "Найти закупку",
        "Поиск закупок",
    )
    LINK_HINTS = ("procurements", "obj_id", "published_procurements")

    def _parse_results(self, html: str) -> list[Tender]:
        """Parse official Rosatom procedure links.

        Rosatom procedure URLs normally carry an opaque obj_id rather than a
        numeric tender ID. The obj_id is therefore used as the stable external
        identifier and the complete official URL is retained for details.
        """
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        soup = BeautifulSoup(html, "html.parser")
        results: list[Tender] = []
        seen: set[str] = set()
        base_host = urlparse(self.BASE_URL).netloc.lower()

        body_text = " ".join(soup.stripped_strings).lower()
        if "web application firewall" in body_text or "временно заблокирован" in body_text:
            logger.warning(
                "rosatom: официальный портал вернул страницу WAF; поиск невозможен без обхода защиты"
            )
            return []

        for anchor in soup.find_all("a", href=True):
            raw_href = str(anchor.get("href", "")).strip()
            href = urljoin(self.BASE_URL, raw_href)
            parsed = urlparse(href)
            if parsed.netloc and parsed.netloc.lower() != base_host:
                continue

            query = parse_qs(parsed.query)
            obj_id = (query.get("obj_id") or [""])[0].strip()
            title = " ".join(anchor.stripped_strings)
            if not obj_id or not title or len(title) < 5:
                continue
            if "procurements" not in href.lower():
                continue
            if obj_id in seen:
                continue

            seen.add(obj_id)
            self._urls[obj_id] = href
            results.append(
                Tender(
                    platform=self.platform,
                    external_id=obj_id,
                    title=title[:1000],
                    url=href,
                    description=title,
                    raw_data={"source": "zakupki.rosatom.ru", "obj_id": obj_id},
                )
            )

        return results

    def _parse_detail(self, html: str, external_id: str, url: str) -> Tender:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        text = " ".join(soup.stripped_strings)
        title_node = soup.find("h1") or soup.find("title")
        title = " ".join(title_node.stripped_strings) if title_node else f"Закупка Росатома {external_id}"

        if "временно заблокирован" in text.lower() or "web application firewall" in text.lower():
            logger.warning("rosatom: WAF при загрузке деталей %s", external_id)
            return Tender(
                platform=self.platform,
                external_id=external_id,
                title=title[:1000],
                url=url,
                description=text[:10000],
                raw_data={"source": url, "waf_blocked": True},
            )

        price = self._extract_price(text)
        deadline = self._extract_date(text)
        customer = ""
        match = re.search(r"Организатор\s*[:\-]\s*(.+?)(?:\s+Контактное лицо|\s+Дата|$)", text, re.I)
        if match:
            customer = match.group(1).strip()[:1000]

        official_number = ""
        match = re.search(r"Номер закупки на официальном сайте ГК «Росатом»\s*[:\-]?\s*(\d+)", text, re.I)
        if match:
            official_number = match.group(1)

        return Tender(
            platform=self.platform,
            external_id=external_id,
            title=title[:1000],
            url=url,
            description=text[:10000],
            price=price,
            deadline=deadline,
            customer=customer,
            raw_data={
                "source": url,
                "obj_id": external_id,
                "official_number": official_number,
            },
        )
