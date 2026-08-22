"""Public collector for the Fabrikant electronic trading platform."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.collectors.browser_public import _BrowserTenderCollector
from src.models.tender import Tender

logger = logging.getLogger(__name__)


class FabrikantCollector(_BrowserTenderCollector):
    """Search public Fabrikant procurement registers (44-FZ and 223-FZ)."""

    platform = "fabrikant"
    BASE_URL = "https://soap2.fabrikant.ru/223/catalog/procedure/published"
    SEARCH_HINTS = ("Поиск", "Найти", "Применить")
    LINK_HINTS = ("/223/procedure/", "/223/catalog/procedure", "procedure")

    def search(self, keywords: list[str], since=None) -> list[Tender]:
        """Search both public Fabrikant sections for each keyword."""
        terms = [str(x).strip() for x in keywords if str(x).strip()]
        if not terms:
            return []

        merged: dict[str, Tender] = {}
        for base_url in (
            "https://soap2.fabrikant.ru/223/catalog/procedure/published",
            "https://soap4.fabrikant.ru/44/catalog/procedure",
        ):
            self.BASE_URL = base_url
            self._urls = {}
            for term in terms:
                results = self._search_one(term)
                for tender in results:
                    merged[tender.unique_key] = tender
                    if len(merged) >= self.max_results:
                        break
                if len(merged) >= self.max_results:
                    break
            if len(merged) >= self.max_results:
                break

        logger.info("fabrikant: найдено %d уникальных процедур", len(merged))
        return list(merged.values())[: self.max_results]

    def _parse_results(self, html: str) -> list[Tender]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[Tender] = []
        seen: set[str] = set()
        base_host = urlparse(self.BASE_URL).netloc.lower()

        for anchor in soup.find_all("a", href=True):
            href = urljoin(self.BASE_URL, str(anchor.get("href", "")).strip())
            parsed = urlparse(href)
            if parsed.netloc.lower() != base_host:
                continue
            if "/procedure/" not in href.lower():
                continue

            title = " ".join(anchor.stripped_strings)
            if not title or len(title) < 5:
                continue
            external_id = self._extract_id(href, title)
            if not external_id or external_id in seen:
                continue

            seen.add(external_id)
            self._urls[external_id] = href
            results.append(
                Tender(
                    platform=self.platform,
                    external_id=external_id,
                    title=title[:1000],
                    url=href,
                    description=title,
                    raw_data={"source": self.BASE_URL},
                )
            )
        return results

    def _parse_detail(self, html: str, external_id: str, url: str) -> Tender:
        """Extract structured Fabrikant fields instead of using the page H1."""
        soup = BeautifulSoup(html, "html.parser")
        text = " ".join(soup.stripped_strings)

        subject = self._field(soup, (
            "предмет закупки", "предмет торгов", "наименование закупки",
            "наименование процедуры", "объект закупки", "наименование предмета",
            "предмет договора", "наименование товара",
        ))
        customer = self._field(soup, (
            "заказчик", "наименование заказчика", "организатор закупки",
            "организатор",
        ))
        region = self._field(soup, (
            "регион", "регион поставки", "место поставки", "место нахождения",
            "адрес поставки", "место проведения",
        ))
        published_at = self._date_field(soup, text, (
            "дата публикации", "дата размещения", "дата создания",
            "дата начала", "дата закупки", "опубликовано",
        ))
        deadline = self._date_field(soup, text, (
            "окончание подачи заявок", "дата окончания подачи заявок",
            "срок подачи заявок", "окончательный срок подачи заявок",
            "дата окончания приема заявок", "прием заявок до",
        ))
        price = self._extract_price(text)

        # Do not expose generic headings such as "Сведения о закупке ..." as
        # the subject when the structured subject is present on the page.
        title = subject or self._clean_title(soup, external_id)
        description = text[:10000]

        tender = Tender(
            platform=self.platform,
            external_id=external_id,
            title=title[:1000],
            url=url,
            description=description,
            price=price,
            deadline=deadline,
            published_at=published_at,
            start_date=published_at,
            region=region or "",
            customer=customer or "",
            raw_data={
                "source": url,
                "published_at": published_at.isoformat() if published_at else None,
                "subject": subject,
                "customer": customer,
                "region": region,
            },
        )
        logger.info(
            "fabrikant: parsed %s | subject=%s | customer=%s | region=%s | published=%s | deadline=%s",
            external_id,
            bool(subject),
            bool(customer),
            bool(region),
            published_at,
            deadline,
        )
        return tender

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip(" :;\t\r\n")

    @classmethod
    def _field(cls, soup: BeautifulSoup, labels: tuple[str, ...]) -> str:
        """Read a value next to a known Russian label from tables/definition lists."""
        wanted = {cls._norm(x).lower() for x in labels}

        for node in soup.find_all(["tr", "dt", "div", "li", "p"]):
            parts = [cls._norm(" ".join(x.stripped_strings)) for x in node.find_all(recursive=False)]
            if len(parts) >= 2 and cls._norm(parts[0]).lower().rstrip(":") in wanted:
                value = cls._norm(" ".join(parts[1:]))
                if value and value.lower() not in wanted:
                    return cls._strip_generic_value(value)

            own = cls._norm(" ".join(node.stripped_strings))
            for label in labels:
                pattern = rf"^{re.escape(label)}\s*:\s*(.+)$"
                match = re.match(pattern, own, re.I)
                if match:
                    return cls._strip_generic_value(match.group(1))

        # Fallback for plain rendered text where labels and values are split
        # only by whitespace/newlines after JavaScript rendering.
        full = "\n".join(cls._norm(x) for x in soup.stripped_strings if cls._norm(x))
        for label in labels:
            match = re.search(rf"(?:^|\n){re.escape(label)}\s*:?\s*([^\n]+)", full, re.I)
            if match:
                value = cls._strip_generic_value(match.group(1))
                if value and value.lower() != label.lower():
                    return value
        return ""

    @staticmethod
    def _strip_generic_value(value: str) -> str:
        value = re.sub(r"\s+", " ", value).strip(" :;|")
        # Do not accidentally return another UI label when two fields are
        # rendered on one line.
        value = re.split(r"\s+(?:Дата|Регион|Заказчик|Предмет|Место|Срок)\s*:", value, maxsplit=1, flags=re.I)[0]
        return value[:1000]

    @classmethod
    def _date_field(cls, soup: BeautifulSoup, text: str, labels: tuple[str, ...]) -> datetime | None:
        value = cls._field(soup, labels)
        date = cls._parse_datetime(value)
        if date:
            return date
        for label in labels:
            match = re.search(
                rf"{re.escape(label)}\s*:?\s*(\d{{1,2}}[./-]\d{{1,2}}[./-]20\d{{2}}(?:\s+\d{{1,2}}:\d{{2}})?)",
                text,
                re.I,
            )
            if match:
                date = cls._parse_datetime(match.group(1))
                if date:
                    return date
        return None

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        if not value:
            return None
        match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?:\s+(\d{1,2}):(\d{2}))?", value)
        if not match:
            return None
        try:
            return datetime(
                int(match.group(3)), int(match.group(2)), int(match.group(1)),
                int(match.group(4) or 0), int(match.group(5) or 0),
            )
        except ValueError:
            return None

    @staticmethod
    def _clean_title(soup: BeautifulSoup, external_id: str) -> str:
        node = soup.find("h1")
        title = " ".join(node.stripped_strings) if node else ""
        if not title:
            node = soup.find("title")
            title = " ".join(node.stripped_strings) if node else ""
        generic = re.sub(r"\s+", " ", title).strip()
        if not generic or re.match(rf"^сведения\s+о\s+закупке\s+{re.escape(external_id)}$", generic, re.I):
            return f"Процедура {external_id}"
        return generic

    @staticmethod
    def _extract_price(text: str) -> float | None:
        for match in re.finditer(
            r"(?:цена|стоимость|НМЦ|начальн\w* цена)[^0-9]{0,60}"
            r"([0-9][0-9\s]{2,}(?:[.,][0-9]{1,2})?)",
            text,
            re.I,
        ):
            try:
                return float(match.group(1).replace(" ", "").replace(",", "."))
            except ValueError:
                continue
        return None
