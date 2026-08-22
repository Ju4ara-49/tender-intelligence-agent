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
                for tender in self._search_one(term):
                    merged[tender.unique_key] = tender
                    if len(merged) >= self.max_results:
                        break
                if len(merged) >= self.max_results:
                    break
            if len(merged) >= self.max_results:
                break

        logger.info("fabrikant: найдено %d уникальных процедур", len(merged))
        return list(merged.values())[: self.max_results]

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip(" :;|\t\r\n")

    @classmethod
    def _column_index(cls, headers: list[str], *names: str) -> int | None:
        normalized = [cls._norm(x).lower() for x in headers]
        for name in names:
            wanted = cls._norm(name).lower()
            for idx, header in enumerate(normalized):
                if wanted == header or wanted in header:
                    return idx
        return None

    @classmethod
    def _parse_results(cls, html: str) -> list[Tender]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[Tender] = []
        seen: set[str] = set()
        base_host = urlparse(cls.BASE_URL).netloc.lower()

        # Fabrikant's public registry already contains most of the fields we
        # need: subject, NMCC, organizer, customer, publication date and
        # application deadline. Previously we discarded all table cells and
        # kept only anchor text, which made every subsequent detail record
        # look almost empty. Parse the row first and use anchor parsing only
        # as a fallback for non-table layouts.
        for table in soup.find_all("table"):
            header_row = table.find("tr")
            if not header_row:
                continue
            header_cells = header_row.find_all(["th", "td"], recursive=False)
            headers = [cls._norm(" ".join(cell.stripped_strings)) for cell in header_cells]
            if not headers:
                continue

            idx_title = cls._column_index(headers, "Наименование", "Предмет закупки")
            idx_price = cls._column_index(headers, "НМЦ", "Начальная (максимальная) цена", "Цена")
            idx_customer = cls._column_index(headers, "Заказчик", "Наименование заказчика")
            idx_region = cls._column_index(headers, "Регион", "Регион заказчика", "Место поставки")
            idx_published = cls._column_index(headers, "Дата публикации", "Дата размещения")
            idx_deadline = cls._column_index(headers, "Завершение подачи", "Окончание подачи", "Срок подачи")

            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"], recursive=False)
                if not cells:
                    continue
                anchors = row.find_all("a", href=True)
                procedure_anchor = None
                for anchor in anchors:
                    href = urljoin(cls.BASE_URL, str(anchor.get("href", "")).strip())
                    if urlparse(href).netloc.lower() == base_host and "/procedure/" in href.lower():
                        procedure_anchor = anchor
                        break
                if not procedure_anchor:
                    continue

                href = urljoin(cls.BASE_URL, str(procedure_anchor.get("href", "")).strip())
                anchor_title = cls._norm(" ".join(procedure_anchor.stripped_strings))
                external_id = cls._extract_id(href, anchor_title)
                if not external_id or external_id in seen:
                    continue

                values = [cls._norm(" ".join(cell.stripped_strings)) for cell in cells]
                title = values[idx_title] if idx_title is not None and idx_title < len(values) else anchor_title
                customer = values[idx_customer] if idx_customer is not None and idx_customer < len(values) else ""
                region = values[idx_region] if idx_region is not None and idx_region < len(values) else ""
                published = cls._parse_datetime(values[idx_published]) if idx_published is not None and idx_published < len(values) else None
                deadline = cls._parse_datetime(values[idx_deadline]) if idx_deadline is not None and idx_deadline < len(values) else None
                price = cls._parse_price_value(values[idx_price]) if idx_price is not None and idx_price < len(values) else None

                seen.add(external_id)
                cls._store_url(external_id, href)
                results.append(Tender(
                    platform=cls.platform,
                    external_id=external_id,
                    title=title[:1000],
                    url=href,
                    description=title,
                    price=price,
                    deadline=deadline,
                    published_at=published,
                    start_date=published,
                    region=region,
                    customer=customer,
                    raw_data={
                        "source": cls.BASE_URL,
                        "search_row": {
                            "headers": headers,
                            "values": values,
                        },
                    },
                ))

        # Fallback for pages whose results are rendered as cards/divs rather
        # than a table. This preserves the previous behavior.
        if results:
            return results
        for anchor in soup.find_all("a", href=True):
            href = urljoin(cls.BASE_URL, str(anchor.get("href", "")).strip())
            parsed = urlparse(href)
            if parsed.netloc.lower() != base_host or "/procedure/" not in href.lower():
                continue
            title = cls._norm(" ".join(anchor.stripped_strings))
            external_id = cls._extract_id(href, title)
            if not title or len(title) < 5 or not external_id or external_id in seen:
                continue
            seen.add(external_id)
            cls._store_url(external_id, href)
            results.append(Tender(
                platform=cls.platform,
                external_id=external_id,
                title=title[:1000],
                url=href,
                description=title,
                raw_data={"source": cls.BASE_URL},
            ))
        return results

    @classmethod
    def _store_url(cls, external_id: str, href: str) -> None:
        # _parse_results is called as an instance method in normal operation;
        # keep this helper intentionally small and let the instance override
        # below when needed.
        pass

    def _parse_results(self, html: str) -> list[Tender]:
        # The implementation above needs access to this collector's _urls.
        # Bind the parsed results and URLs here while retaining a clean parser.
        soup = BeautifulSoup(html, "html.parser")
        results: list[Tender] = []
        seen: set[str] = set()
        base_host = urlparse(self.BASE_URL).netloc.lower()

        for table in soup.find_all("table"):
            header_row = table.find("tr")
            if not header_row:
                continue
            header_cells = header_row.find_all(["th", "td"], recursive=False)
            headers = [self._norm(" ".join(cell.stripped_strings)) for cell in header_cells]
            if not headers:
                continue
            idx_title = self._column_index(headers, "Наименование", "Предмет закупки")
            idx_price = self._column_index(headers, "НМЦ", "Начальная (максимальная) цена", "Цена")
            idx_customer = self._column_index(headers, "Заказчик", "Наименование заказчика")
            idx_region = self._column_index(headers, "Регион", "Регион заказчика", "Место поставки")
            idx_published = self._column_index(headers, "Дата публикации", "Дата размещения")
            idx_deadline = self._column_index(headers, "Завершение подачи", "Окончание подачи", "Срок подачи")

            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"], recursive=False)
                anchors = row.find_all("a", href=True)
                procedure_anchor = None
                for anchor in anchors:
                    href = urljoin(self.BASE_URL, str(anchor.get("href", "")).strip())
                    if urlparse(href).netloc.lower() == base_host and "/procedure/" in href.lower():
                        procedure_anchor = anchor
                        break
                if not procedure_anchor:
                    continue
                href = urljoin(self.BASE_URL, str(procedure_anchor.get("href", "")).strip())
                anchor_title = self._norm(" ".join(procedure_anchor.stripped_strings))
                external_id = self._extract_id(href, anchor_title)
                if not external_id or external_id in seen:
                    continue
                values = [self._norm(" ".join(cell.stripped_strings)) for cell in cells]
                title = values[idx_title] if idx_title is not None and idx_title < len(values) else anchor_title
                customer = values[idx_customer] if idx_customer is not None and idx_customer < len(values) else ""
                region = values[idx_region] if idx_region is not None and idx_region < len(values) else ""
                published = self._parse_datetime(values[idx_published]) if idx_published is not None and idx_published < len(values) else None
                deadline = self._parse_datetime(values[idx_deadline]) if idx_deadline is not None and idx_deadline < len(values) else None
                price = self._parse_price_value(values[idx_price]) if idx_price is not None and idx_price < len(values) else None
                seen.add(external_id)
                self._urls[external_id] = href
                results.append(Tender(
                    platform=self.platform,
                    external_id=external_id,
                    title=title[:1000],
                    url=href,
                    description=title,
                    price=price,
                    deadline=deadline,
                    published_at=published,
                    start_date=published,
                    region=region,
                    customer=customer,
                    raw_data={"source": self.BASE_URL, "search_row": {"headers": headers, "values": values}},
                ))
        if results:
            return results

        for anchor in soup.find_all("a", href=True):
            href = urljoin(self.BASE_URL, str(anchor.get("href", "")).strip())
            parsed = urlparse(href)
            if parsed.netloc.lower() != base_host or "/procedure/" not in href.lower():
                continue
            title = self._norm(" ".join(anchor.stripped_strings))
            external_id = self._extract_id(href, title)
            if not title or len(title) < 5 or not external_id or external_id in seen:
                continue
            seen.add(external_id)
            self._urls[external_id] = href
            results.append(Tender(platform=self.platform, external_id=external_id, title=title[:1000], url=href, description=title, raw_data={"source": self.BASE_URL}))
        return results

    def _parse_detail(self, html: str, external_id: str, url: str) -> Tender:
        soup = BeautifulSoup(html, "html.parser")
        text = self._norm(" ".join(soup.stripped_strings))
        subject = self._field(soup, ("предмет закупки", "предмет торгов", "наименование закупки", "наименование процедуры", "объект закупки", "предмет договора", "наименование товара"))
        customer = self._field(soup, ("заказчик", "наименование заказчика", "организатор закупки", "организатор"))
        region = self._field(soup, ("регион", "регион заказчика", "регион поставки", "место поставки", "место нахождения", "адрес поставки", "место проведения"))
        published = self._date_field(soup, text, ("дата публикации", "дата размещения", "дата создания", "дата начала", "дата закупки", "опубликовано"))
        deadline = self._date_field(soup, text, ("окончание подачи заявок", "дата окончания подачи заявок", "срок подачи заявок", "окончательный срок подачи заявок", "дата окончания приема заявок", "прием заявок до", "завершение подачи"))
        price = self._extract_price(text)
        title = subject or self._clean_title(soup, external_id)
        return Tender(
            platform=self.platform,
            external_id=external_id,
            title=title[:1000],
            url=url,
            description=text[:10000],
            price=price,
            deadline=deadline,
            published_at=published,
            start_date=published,
            region=region,
            customer=customer,
            raw_data={"source": url, "published_at": published.isoformat() if published else None, "subject": subject, "customer": customer, "region": region},
        )

    _FIELD_LABELS = (
        "предмет закупки", "предмет торгов", "наименование закупки", "наименование процедуры", "объект закупки", "предмет договора", "наименование товара",
        "заказчик", "наименование заказчика", "организатор закупки", "организатор", "регион", "регион заказчика", "регион поставки", "место поставки", "место нахождения", "адрес поставки", "место проведения",
        "дата публикации", "дата размещения", "дата создания", "дата начала", "дата закупки", "опубликовано", "окончание подачи заявок", "дата окончания подачи заявок", "срок подачи заявок", "окончательный срок подачи заявок", "дата окончания приема заявок", "прием заявок до", "завершение подачи",
        "начальная цена", "начальная максимальная цена", "цена", "НМЦ",
    )

    @classmethod
    def _field(cls, soup: BeautifulSoup, labels: tuple[str, ...]) -> str:
        wanted = {cls._norm(x).lower().rstrip(":") for x in labels}
        for node in soup.find_all(["tr", "dt", "div", "li", "p"]):
            children = [cls._norm(" ".join(x.stripped_strings)) for x in node.find_all(recursive=False)]
            children = [x for x in children if x]
            if len(children) >= 2 and children[0].lower().rstrip(":") in wanted:
                value = cls._strip_value(" ".join(children[1:]))
                if value and value.lower() not in wanted:
                    return value
            own = cls._norm(" ".join(node.stripped_strings))
            for label in labels:
                m = re.match(rf"^{re.escape(label)}\s*:\s*(.+)$", own, re.I)
                if m:
                    value = cls._strip_value(m.group(1))
                    if value and value.lower() != label.lower():
                        return value

        lines = [cls._norm(x) for x in soup.stripped_strings if cls._norm(x)]
        boundaries = "|".join(re.escape(x) for x in cls._FIELD_LABELS)
        for i, line in enumerate(lines):
            for label in labels:
                m = re.match(rf"^{re.escape(label)}\s*:?\s*(.*)$", line, re.I)
                if not m:
                    continue
                value = cls._strip_value(m.group(1))
                if value and value.lower() != label.lower():
                    return value
                for following in lines[i + 1:i + 8]:
                    if re.match(rf"^(?:{boundaries})\s*:?", following, re.I):
                        break
                    value = cls._strip_value(following)
                    if value:
                        return value
        return ""

    @staticmethod
    def _strip_value(value: str) -> str:
        value = re.sub(r"\s+", " ", value).strip(" :;|")
        return re.split(r"\s+(?:Дата|Регион|Заказчик|Предмет|Место|Срок|Организатор|Цена|НМЦ)\s*:", value, maxsplit=1, flags=re.I)[0][:1000]

    @classmethod
    def _date_field(cls, soup: BeautifulSoup, text: str, labels: tuple[str, ...]) -> datetime | None:
        value = cls._field(soup, labels)
        parsed = cls._parse_datetime(value)
        if parsed:
            return parsed
        for label in labels:
            m = re.search(rf"{re.escape(label)}\s*:?\s*(\d{{1,2}}[./-]\d{{1,2}}[./-]20\d{{2}}(?:\s+\d{{1,2}}:\d{{2}})?|20\d{{2}}[./-]\d{{1,2}}[./-]\d{{1,2}}(?:\s+\d{{1,2}}:\d{{2}})?)", text, re.I)
            if m:
                parsed = cls._parse_datetime(m.group(1))
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        if not value:
            return None
        m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?:\s+(\d{1,2}):(\d{2}))?", value)
        if m:
            try:
                return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), int(m.group(4) or 0), int(m.group(5) or 0))
            except ValueError:
                return None
        m = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})(?:[T\s]+(\d{1,2}):(\d{2}))?", value)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4) or 0), int(m.group(5) or 0))
            except ValueError:
                return None
        return None

    @classmethod
    def _parse_price_value(cls, value: str) -> float | None:
        if not value:
            return None
        m = re.search(r"[0-9][0-9\s\u00a0]*(?:[.,][0-9]{1,2})?", value)
        if not m:
            return None
        try:
            return float(m.group(0).replace(" ", "").replace("\u00a0", "").replace(",", "."))
        except ValueError:
            return None

    @classmethod
    def _extract_price(cls, text: str) -> float | None:
        for match in re.finditer(r"(?:цена|стоимость|НМЦ|начальн\w* цена)[^0-9]{0,60}([0-9][0-9\s\u00a0]{2,}(?:[.,][0-9]{1,2})?)", text, re.I):
            value = cls._parse_price_value(match.group(1))
            if value is not None:
                return value
        return None

    @staticmethod
    def _clean_title(soup: BeautifulSoup, external_id: str) -> str:
        node = soup.find("h1") or soup.find("title")
        title = " ".join(node.stripped_strings) if node else ""
        title = re.sub(r"\s+", " ", title).strip()
        if not title or re.match(rf"^сведения\s+о\s+закупке\s+{re.escape(external_id)}$", title, re.I):
            return f"Процедура {external_id}"
        return title

    @staticmethod
    def _extract_id(href: str, title: str) -> str | None:
        patterns = [
            r"(?:procedure|tender|purchase)[^0-9]{0,30}(\d{5,})",
            r"(?:/|#)l(\d{6,})(?:[-/]|$)",
            r"(?:/|#)(\d{6,})(?:/|$)",
            r"\b(\d{7,})\b",
        ]
        for source in (href, title):
            for pattern in patterns:
                match = re.search(pattern, source, re.I)
                if match:
                    return match.group(1)
        return None
