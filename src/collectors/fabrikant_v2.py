"""Robust public Fabrikant collector.

The public Fabrikant registry exposes customer, publication date and request
end date directly in its result table. The previous collector threw those
cells away and therefore sent almost empty Tender objects to enrichment.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.collectors.browser_public import _BrowserTenderCollector
from src.models.tender import Tender

logger = logging.getLogger(__name__)


class FabrikantV2Collector(_BrowserTenderCollector):
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

    def _parse_results(self, html: str) -> list[Tender]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[Tender] = []
        seen: set[str] = set()
        base_host = urlparse(self.BASE_URL).netloc.lower()

        # 44-FZ/223-FZ public registry rows contain structured fields. Parse
        # those cells instead of relying on the detail page for basic data.
        for table in soup.find_all("table"):
            header_row = table.find("tr")
            if not header_row:
                continue
            header_cells = header_row.find_all(["th", "td"], recursive=False)
            headers = [self._norm(" ".join(c.stripped_strings)) for c in header_cells]
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
                if not cells:
                    continue
                anchor = self._procedure_anchor(row, base_host)
                if anchor is None:
                    continue
                href = urljoin(self.BASE_URL, str(anchor.get("href", "")).strip())
                anchor_title = self._norm(" ".join(anchor.stripped_strings))
                external_id = self._extract_id(href, anchor_title)
                if not external_id or external_id in seen:
                    continue

                values = [self._norm(" ".join(c.stripped_strings)) for c in cells]
                title = self._cell(values, idx_title) or anchor_title
                customer = self._cell(values, idx_customer)
                region = self._cell(values, idx_region)
                published = self._parse_datetime(self._cell(values, idx_published))
                deadline = self._parse_datetime(self._cell(values, idx_deadline))
                price = self._parse_price(self._cell(values, idx_price))

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
                    raw_data={
                        "source": self.BASE_URL,
                        "search_row": {"headers": headers, "values": values},
                    },
                ))

        if results:
            return results

        # Card/div fallback for alternative Fabrikant layouts.
        for anchor in soup.find_all("a", href=True):
            href = urljoin(self.BASE_URL, str(anchor.get("href", "")).strip())
            if urlparse(href).netloc.lower() != base_host or "/procedure/" not in href.lower():
                continue
            title = self._norm(" ".join(anchor.stripped_strings))
            external_id = self._extract_id(href, title)
            if not title or len(title) < 5 or not external_id or external_id in seen:
                continue
            seen.add(external_id)
            self._urls[external_id] = href
            results.append(Tender(
                platform=self.platform,
                external_id=external_id,
                title=title[:1000],
                url=href,
                description=title,
                raw_data={"source": self.BASE_URL},
            ))
        return results

    @staticmethod
    def _procedure_anchor(row, base_host):
        for anchor in row.find_all("a", href=True):
            href = str(anchor.get("href", "")).strip()
            full = urljoin("https://soap4.fabrikant.ru", href)
            if urlparse(full).netloc.lower() == base_host and "/procedure/" in full.lower():
                return anchor
        return None

    @staticmethod
    def _cell(values: list[str], index: int | None) -> str:
        return values[index] if index is not None and index < len(values) else ""

    @staticmethod
    def _parse_price(value: str) -> float | None:
        if not value:
            return None
        match = re.search(r"[0-9][0-9\s\u00a0]*(?:[.,][0-9]{1,2})?", value)
        if not match:
            return None
        try:
            return float(match.group(0).replace(" ", "").replace("\u00a0", "").replace(",", "."))
        except ValueError:
            return None

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        if not value:
            return None
        match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?:\s+(\d{1,2}):(\d{2})(?::\d{2})?)?", value)
        if match:
            try:
                return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)), int(match.group(4) or 0), int(match.group(5) or 0))
            except ValueError:
                return None
        match = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})(?:[T\s]+(\d{1,2}):(\d{2}))?", value)
        if match:
            try:
                return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4) or 0), int(match.group(5) or 0))
            except ValueError:
                return None
        return None

    @classmethod
    def _extract_price(cls, text: str) -> float | None:
        for match in re.finditer(r"(?:цена|стоимость|НМЦ|начальн\w* цена)[^0-9]{0,60}([0-9][0-9\s\u00a0]{2,}(?:[.,][0-9]{1,2})?)", text, re.I):
            value = cls._parse_price(match.group(1))
            if value is not None:
                return value
        return None

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
            raw_data={"source": url, "subject": subject, "customer": customer, "region": region},
        )

    _FIELD_LABELS = (
        "предмет закупки", "предмет торгов", "наименование закупки", "наименование процедуры", "объект закупки", "предмет договора", "наименование товара",
        "заказчик", "наименование заказчика", "организатор закупки", "организатор", "регион", "регион заказчика", "регион поставки", "место поставки", "место нахождения", "адрес поставки", "место проведения",
        "дата публикации", "дата размещения", "дата создания", "дата начала", "дата закупки", "опубликовано", "окончание подачи заявок", "дата окончания подачи заявок", "срок подачи заявок", "окончательный срок подачи заявок", "дата окончания приема заявок", "прием заявок до", "завершение подачи",
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
                match = re.match(rf"^{re.escape(label)}\s*:\s*(.+)$", own, re.I)
                if match:
                    value = cls._strip_value(match.group(1))
                    if value and value.lower() != label.lower():
                        return value

        lines = [cls._norm(x) for x in soup.stripped_strings if cls._norm(x)]
        boundaries = "|".join(re.escape(x) for x in cls._FIELD_LABELS)
        for i, line in enumerate(lines):
            for label in labels:
                match = re.match(rf"^{re.escape(label)}\s*:?\s*(.*)$", line, re.I)
                if not match:
                    continue
                value = cls._strip_value(match.group(1))
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
            match = re.search(rf"{re.escape(label)}\s*:?\s*(\d{{1,2}}[./-]\d{{1,2}}[./-]20\d{{2}}(?:\s+\d{{1,2}}:\d{{2}}(?::\d{{2}})?)?)", text, re.I)
            if match:
                parsed = cls._parse_datetime(match.group(1))
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _clean_title(soup: BeautifulSoup, external_id: str) -> str:
        node = soup.find("h1") or soup.find("title")
        title = " ".join(node.stripped_strings) if node else ""
        title = re.sub(r"\s+", " ", title).strip()
        return title if title else f"Процедура {external_id}"

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
