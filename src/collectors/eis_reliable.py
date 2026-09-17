"""EIS collector adapter that guarantees unified commercial-condition fields."""
from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
import re

import requests
from bs4 import BeautifulSoup

from src.collectors.base import CollectorUnavailableError
from src.collectors.eis_zakupki import BASE_URL, EisZakupkiCollector, SEARCH_URL
from src.models.tender import Tender
from src.collectors.tenderguru_fallback import search as tenderguru_search


class ReliableEisZakupkiCollector(EisZakupkiCollector):
    """EIS collector with a final commercial-terms enrichment pass."""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        # External aggregators are opt-in. The default must remain fail-closed:
        # returning third-party tenders under the EIS platform identity can make
        # a transport outage look like a successful first-party search.
        self.allow_external_fallback = bool(
            self.config.get("allow_external_fallback", False)
        )

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

        if self.allow_external_fallback:
            fallback: list[Tender] = []
            for keyword in clean_keywords:
                try:
                    fallback.extend(
                        tenderguru_search(
                            platform=self.platform,
                            keyword=keyword,
                            timeout=min(max(self.timeout, 5), 20),
                            max_results=self.records_per_page * self.max_pages,
                        )
                    )
                except Exception:
                    continue
            if fallback:
                unique = {item.unique_key: item for item in fallback}
                return list(unique.values())

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
            raise CollectorUnavailableError(
                f"eis: search endpoint unavailable: {type(detail).__name__}: {detail}"
            ) from detail
        if self._has_captcha(probe.text):
            raise CollectorUnavailableError("eis: search endpoint returned CAPTCHA/bot protection")
        return super().search(clean_keywords, since=since)

    def _search_rss(self, keyword: str, since: datetime | None) -> list[Tender]:
        """Use EIS's lightweight public RSS search instead of the heavy HTML registry."""
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

    @staticmethod
    def _parse_datetime_value(value: str) -> datetime | None:
        match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?:[^0-9]{0,12}(\d{1,2}):(\d{2}))?", value)
        if match:
            try:
                return datetime(
                    int(match.group(3)), int(match.group(2)), int(match.group(1)),
                    int(match.group(4) or 0), int(match.group(5) or 0),
                )
            except ValueError:
                return None
        match = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})(?:[T\s]+(\d{1,2}):(\d{2}))?", value)
        if match:
            try:
                return datetime(
                    int(match.group(1)), int(match.group(2)), int(match.group(3)),
                    int(match.group(4) or 0), int(match.group(5) or 0),
                )
            except ValueError:
                return None
        return None

    @classmethod
    def _extract_procedure_dates(cls, text: str) -> tuple[datetime | None, datetime | None]:
        """Extract start/end without allowing whitespace to swallow the time."""
        text = re.sub(r"\s+", " ", str(text or ""))
        date_pattern = r"\d{1,2}[./-]\d{1,2}[./-]20\d{2}(?:\s+\d{1,2}:\d{2})?"
        start_labels = (
            "Дата начала подачи заявок", "Начало подачи заявок",
            "Дата начала приема заявок", "Начало приема заявок",
            "Дата начала подачи", "Начало приема",
        )
        end_labels = (
            "Дата окончания подачи заявок", "Окончание подачи заявок",
            "Дата окончания приема заявок", "Окончание приема заявок",
            "Дата окончания подачи", "Окончание приема",
        )

        def find(labels: tuple[str, ...]) -> datetime | None:
            label = "|".join(re.escape(item) for item in labels)
            match = re.search(rf"(?:{label})\s*[:\-]?\s*({date_pattern})", text, re.I)
            if not match:
                return None
            return cls._parse_datetime_value(match.group(1))

        return find(start_labels), find(end_labels)

    @staticmethod
    def _is_navigation_noise(value: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
        markers = (
            "протоколы", "личный кабинет", "сведения о закупке",
            "реестровый номер извещения", "реестровый номер", "меню",
            "поиск закупок", "войти", "регистрация",
        )
        return any(marker in normalized for marker in markers)

    @classmethod
    def _clean_customer_candidate(cls, value: str) -> str:
        value = cls._clean_text(value).strip(" :;-–—")
        if len(value) < 5 or len(value) > 1000 or cls._is_navigation_noise(value):
            return ""
        # Stop accidental concatenation with the next EIS section.
        for marker in (
            " Место нахождения", " Почтовый адрес", " Адрес электронной почты",
            " Контактный телефон", " Ответственное должностное лицо",
            " Начальная цена", " НМЦК", " Регион", " Объект закупки",
        ):
            if marker.casefold() in value.casefold():
                value = value[:value.casefold().find(marker.casefold())].strip()
        return value[:1000]

    @classmethod
    def _extract_customer_from_soup(cls, soup: BeautifulSoup) -> str:
        """Extract an actual organization and reject EIS navigation/footer text."""
        organization_prefixes = (
            "ГОСУДАРСТВЕННОЕ ", "МУНИЦИПАЛЬНОЕ ", "ФЕДЕРАЛЬНОЕ ",
            "БЮДЖЕТНОЕ ", "АВТОНОМНОЕ ", "КАЗЕННОЕ ", "ОБЛАСТНОЕ ",
            "КРАЕВОЕ ", "РЕСПУБЛИКАНСКОЕ ", "ООО ", "АО ", "ПАО ",
            "ОАО ", "ЗАО ", "ИП ",
        )
        for element in soup.select("td.tableBlock__col_header, .tableBlock__col_header"):
            candidate = cls._clean_customer_candidate(element.get_text(" ", strip=True))
            if not candidate:
                continue
            if any(candidate.upper().startswith(prefix) for prefix in organization_prefixes):
                return candidate

        text = cls._clean_text(soup.get_text(" ", strip=True))
        patterns = (
            r"(?:^|\s)Заказчик\s*[:\-]?\s*(.+?)(?=\s+(?:Место нахождения|Почтовый адрес|Адрес электронной почты|Контактный телефон|Ответственное должностное лицо|Начальная цена|НМЦК|Регион|Объект закупки)\b|$)",
            r"Заказчик\s*[:\-]?\s*(.+?)(?=\s+(?:Сведения о закупке|Реестровый номер|Информация о процедуре)\b)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                candidate = cls._clean_customer_candidate(match.group(1))
                if candidate:
                    return candidate
        return ""

    @classmethod
    def _extract_detail_price(cls, text: str) -> float | None:
        labels = (
            "Начальная (максимальная) цена договора", "Начальная максимальная цена договора",
            "Начальная цена договора", "Начальная цена", "НМЦК", "Цена договора",
            "Общая стоимость закупки", "Максимальная цена договора",
        )
        for label in labels:
            match = re.search(
                rf"{re.escape(label)}\s*[:\-]?\s*([0-9\s\u00a0]+(?:[.,][0-9]{{1,2}})?)\s*(?:₽|руб\.?|рублей|RUB|р\.?)(?!\w)",
                text,
                re.I,
            )
            if not match:
                continue
            try:
                value = float(match.group(1).replace(" ", "").replace("\u00a0", "").replace(",", "."))
            except ValueError:
                continue
            if value > 0:
                return value
        return None

    def _parse_details_page(self, soup: BeautifulSoup, external_id: str, url: str) -> Tender | None:
        """Parse both 44-FZ and 223-FZ pages and reject 223 navigation stubs."""
        text = self._clean_text(soup.get_text(" ", strip=True))
        if not text:
            return None

        law_type = self._extract_law_type(text)
        title = self._extract_labeled_value(
            text,
            ["Объект закупки", "Наименование объекта закупки", "Наименование закупки", "Предмет договора"],
        )
        title = self._clean_text(title)
        if not title or self._is_navigation_noise(title):
            title = self._extract_between(text, "Объект закупки", "Заказчик")
        if not title or self._is_navigation_noise(title):
            title = self._extract_between(text, "Наименование закупки", "Заказчик")
        title = self._clean_text(title)
        if self._is_navigation_noise(title):
            title = ""

        customer = self._extract_customer_from_soup(soup)
        if not customer:
            customer = self._extract_customer_from_text(text)
        customer = self._clean_customer_candidate(customer)

        price = self._extract_detail_price(text)
        published_at = self._extract_detail_datetime(text, ["Размещено", "Дата размещения", "Дата публикации", "Опубликовано"])
        start_date, end_date = self._extract_procedure_dates(text)
        region = self._extract_region_from_soup(soup) or self._extract_region_from_text(text)
        procurement_method = self._extract_procurement_method(text)
        status = self._extract_status(text)
        commercial = self._extract_commercial_conditions(text)

        # A 223 endpoint can return a navigation shell/stub with HTTP 200.
        # Do not treat that shell as a successfully parsed tender.
        meaningful = any((customer, price is not None, published_at, start_date, end_date, region))
        if not title or not meaningful:
            return None

        return Tender(
            platform=self.platform,
            external_id=external_id,
            title=title[:1000],
            url=url,
            description=self._extract_description(text)[:10000],
            price=price,
            currency="RUB",
            start_date=start_date,
            end_date=end_date,
            deadline=end_date,
            published_at=published_at,
            region=region,
            customer=customer,
            law_type=law_type,
            advance_required=bool(commercial["advance_required"]),
            advance_percent=commercial["advance_percent"],
            postpayment_days=commercial["postpayment_days"],
            application_security_percent=commercial["application_security_percent"],
            contract_security_percent=commercial["contract_security_percent"],
            raw_data={
                "details_loaded": True,
                "source_url": url,
                "procurement_method": procurement_method,
                "status": status,
                "commercial_conditions": commercial,
                "details": text[:20000],
            },
        )

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
        tender._persist_normalized_fields()
        return tender
