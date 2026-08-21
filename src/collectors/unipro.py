"""Сборщик публичных уведомлений о закупках ПАО «Юнипро»."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector
from src.models.tender import Tender

logger = logging.getLogger(__name__)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


class UniproCollector(BaseCollector):
    """Собирает публичные объявления со страницы закупок UniPro."""

    platform = "unipro"
    BASE_URL = "https://www.unipro.energy"
    ANNOUNCEMENT_URL = f"{BASE_URL}/purchase/announcement/"

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        self.timeout = int(self.config.get("timeout_seconds", 30))
        self.max_pages = int(self.config.get("max_pages", 5))
        self.request_delay_seconds = float(
            self.config.get("request_delay_seconds", 2)
        )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            }
        )
        self._tender_urls: dict[str, str] = {}

    def search(
        self,
        keywords: list[str],
        since: datetime | None = None,
    ) -> list[Tender]:
        """Загрузить ленту объявлений и отобрать процедуры по ключевым словам."""

        results: dict[str, Tender] = {}
        normalized_keywords = [
            self._normalize_text(value)
            for value in keywords
            if self._normalize_text(value)
        ]
        normalized_since = self._normalize_datetime(since) if since else None

        for page_number in range(1, self.max_pages + 1):
            try:
                response = self._get(self._build_page_url(page_number))
            except requests.RequestException as exc:
                logger.warning("ЮНИПРО: ошибка страницы %d: %s", page_number, exc)
                continue

            page_tenders = self._parse_listing_page(response.text)
            logger.info(
                "ЮНИПРО: страница %d: процедур=%d",
                page_number,
                len(page_tenders),
            )
            if not page_tenders:
                break

            dated_tenders = []
            for tender in page_tenders:
                if tender.published_at:
                    dated_tenders.append(tender.published_at)
                if (
                    normalized_since
                    and tender.published_at
                    and self._normalize_datetime(tender.published_at) < normalized_since
                ):
                    continue
                if normalized_keywords and not self._matches_keywords(
                    tender,
                    normalized_keywords,
                ):
                    continue

                results[tender.unique_key] = tender
                self._tender_urls[tender.external_id] = tender.url

            if normalized_since and dated_tenders:
                newest = max(self._normalize_datetime(value) for value in dated_tenders)
                if newest < normalized_since:
                    break

            if page_number < self.max_pages and self.request_delay_seconds > 0:
                time.sleep(self.request_delay_seconds)

        logger.info("ЮНИПРО: найдено %d уникальных процедур", len(results))
        return list(results.values())

    def get_details(self, external_id: str) -> Tender | None:
        """Получить публичную карточку процедуры по её номеру ЗП."""

        external_id = str(external_id or "").strip().upper()
        if not external_id:
            return None

        url = self._tender_urls.get(external_id) or self._find_detail_url(external_id)
        if not url:
            logger.warning("ЮНИПРО: URL карточки не найден: %s", external_id)
            return None

        try:
            response = self._get(url)
        except requests.RequestException as exc:
            logger.warning("ЮНИПРО: ошибка карточки %s: %s", external_id, exc)
            return None

        return self._parse_detail_page(external_id, url, response.text)

    def _get(self, url: str) -> requests.Response:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response

    def _find_detail_url(self, external_id: str) -> str | None:
        """Найти карточку в публичной ленте, если search не вызывался."""

        for page_number in range(1, self.max_pages + 1):
            try:
                response = self._get(self._build_page_url(page_number))
            except requests.RequestException:
                continue

            for tender in self._parse_listing_page(response.text):
                self._tender_urls[tender.external_id] = tender.url
                if tender.external_id == external_id:
                    return tender.url
        return None

    @classmethod
    def _build_page_url(cls, page_number: int) -> str:
        if page_number <= 1:
            return cls.ANNOUNCEMENT_URL
        return f"{cls.ANNOUNCEMENT_URL}?PAGEN_1={page_number}"

    def _parse_listing_page(self, html: str) -> list[Tender]:
        """Разобрать фактическую двухстрочную таблицу `#table_procurement`."""

        soup = BeautifulSoup(html, "html.parser")
        table = soup.select_one("#table_procurement")
        if table is None:
            return []

        rows = table.find_all("tr", recursive=False)
        results: list[Tender] = []
        for index, row in enumerate(rows):
            title_cell = row.select_one("td.table_title")
            time_cell = row.select_one("td.table_time")
            if title_cell is None or time_cell is None:
                continue

            link = None
            for next_row in rows[index + 1 : index + 3]:
                link = next_row.select_one("a.news_button[href]")
                if link is not None:
                    break
                if next_row.select_one("td.table_title") is not None:
                    break
            if link is None:
                continue

            listing_title = self._clean_text(title_cell.get_text(" ", strip=True))
            external_id = self._extract_external_id(listing_title)
            if not external_id:
                continue

            title = self._clean_title(listing_title, external_id)
            if not title:
                continue

            date_values = self._extract_dates_from_listing(
                time_cell.get_text(" ", strip=True)
            )
            url = urljoin(self.BASE_URL, str(link.get("href", "")).strip())
            if not url:
                continue

            results.append(
                Tender(
                    platform=self.platform,
                    external_id=external_id,
                    title=title,
                    url=url,
                    description=title,
                    published_at=date_values[0],
                    deadline=date_values[1],
                    customer=self._extract_listing_customer(title),
                    raw_data={
                        "source": "unipro.energy",
                        "listing_url": self.ANNOUNCEMENT_URL,
                        "detail_url": url,
                        "listing_text": listing_title,
                    },
                )
            )
        return results

    def _parse_detail_page(
        self,
        external_id: str,
        url: str,
        html: str,
    ) -> Tender | None:
        soup = BeautifulSoup(html, "html.parser")
        content = soup.select_one("div.procurement")
        if content is None:
            logger.warning("ЮНИПРО: блок процедуры не найден: %s", external_id)
            return None

        text = self._clean_text(content.get_text(" ", strip=True))
        title_node = content.select_one("h1")
        title = self._clean_title(
            title_node.get_text(" ", strip=True) if title_node else "",
            external_id,
        )
        if not title:
            title = self._extract_labeled_value(text, "ПРЕДМЕТ ЗАКУПКИ")
        if not title:
            title = f"Закупка Юнипро {external_id}"

        start_date, deadline = self._extract_procedure_dates(text)
        published_at = self._extract_published_at(text)
        customer = self._extract_labeled_value(text, "ЗАКАЗЧИК")
        organizer = self._extract_labeled_value(text, "ОРГАНИЗАТОР")
        region = self._extract_labeled_value(text, "ПОЧТОВЫЙ АДРЕС")
        price = self._extract_price(text)
        procurement_method = self._extract_procurement_method(text)
        commercial = self._extract_commercial_conditions(text)
        law_type = "223-ФЗ" if "223-fz" in text.lower() else ""

        return Tender(
            platform=self.platform,
            external_id=external_id,
            title=title[:1000],
            url=url,
            description=text[:10000],
            price=price,
            currency="RUB",
            start_date=start_date,
            end_date=deadline,
            published_at=published_at,
            deadline=deadline,
            region=region[:1000],
            customer=(customer or organizer)[:1000],
            law_type=law_type,
            advance_required=bool(commercial["advance_required"]),
            advance_percent=commercial["advance_percent"],
            postpayment_days=commercial["postpayment_days"],
            application_security_percent=commercial[
                "application_security_percent"
            ],
            contract_security_percent=commercial[
                "contract_security_percent"
            ],
            raw_data={
                "source": "unipro.energy",
                "details_loaded": True,
                "source_url": url,
                "procurement_method": procurement_method,
                "organizer": organizer,
                "commercial_conditions": commercial,
            },
        )

    @staticmethod
    def _extract_external_id(text: str) -> str:
        match = re.search(r"\b(ЗП\d{5,})\b", text or "", re.IGNORECASE)
        return match.group(1).upper() if match else ""

    @staticmethod
    def _clean_title(value: str, external_id: str) -> str:
        title = UniproCollector._clean_text(value)
        title = re.sub(
            r"\s*\(?\s*" + re.escape(external_id) + r"\s*\)?\s*$",
            "",
            title,
            flags=re.IGNORECASE,
        )
        return title.strip(" .,:;—-")[:1000]

    @staticmethod
    def _extract_listing_customer(title: str) -> str:
        match = re.search(r"\bПАО\s+[«\"]?Юнипро", title, re.IGNORECASE)
        return match.group(0) if match else ""

    @staticmethod
    def _extract_dates_from_listing(text: str) -> tuple[datetime | None, datetime | None]:
        values = re.findall(
            r"\b\d{2}\.\d{2}\.\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?\b",
            text or "",
        )
        published = UniproCollector._parse_datetime(values[0]) if values else None
        deadline = UniproCollector._parse_datetime(values[1]) if len(values) > 1 else None
        return published, deadline

    @staticmethod
    def _extract_labeled_value(text: str, label: str) -> str:
        match = re.search(
            re.escape(label) + r"\s*:\s*(.+?)(?=\s+[А-ЯЁ][А-ЯЁ\s]{3,}:|$)",
            text,
            re.IGNORECASE,
        )
        return UniproCollector._clean_text(match.group(1)) if match else ""

    @staticmethod
    def _extract_procedure_dates(text: str) -> tuple[datetime | None, datetime | None]:
        match = re.search(
            r"Проведение закупки\s*:\s*"
            r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}(?::\d{2})?)\s*-\s*"
            r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}(?::\d{2})?)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None, None
        return (
            UniproCollector._parse_datetime(match.group(1)),
            UniproCollector._parse_datetime(match.group(2)),
        )

    @staticmethod
    def _extract_published_at(text: str) -> datetime | None:
        match = re.search(r"Дата опубликования\s*:\s*(\d{2}\.\d{2}\.\d{4})", text)
        return UniproCollector._parse_datetime(match.group(1)) if match else None

    @staticmethod
    def _extract_procurement_method(text: str) -> str:
        match = re.search(
            r"ПОРЯДОК ПРОВЕДЕНИЯ\s+([А-ЯЁа-яё\s-]+?)\s*:",
            text,
        )
        return UniproCollector._clean_text(match.group(1)).title() if match else ""

    @staticmethod
    def _extract_price(text: str) -> float | None:
        for pattern in (
            r"(?:НМЦК|НМЦ|начальная\s+цена|цена закупки|стоимость)"
            r"[^\d]{0,100}(\d[\d\s\u00a0]*(?:[,.]\d{1,2})?)\s*(?:руб\.?|₽)",
            r"(\d[\d\s\u00a0]*(?:[,.]\d{1,2})?)\s*(?:руб\.?|₽)",
        ):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(" ", "").replace("\u00a0", "").replace(",", "."))
                except ValueError:
                    continue
        return None

    @staticmethod
    def _extract_commercial_conditions(text: str) -> dict[str, object]:
        result: dict[str, object] = {
            "advance_required": False,
            "advance_percent": None,
            "postpayment_days": None,
            "application_security_percent": None,
            "contract_security_percent": None,
        }
        for pattern in (
            r"(?:аванс|предоплат\w*)[^.]{0,200}?(\d+(?:[.,]\d+)?)\s*%",
            r"(\d+(?:[.,]\d+)?)\s*%[^.]{0,200}?(?:аванс|предоплат\w*)",
        ):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["advance_required"] = True
                result["advance_percent"] = float(match.group(1).replace(",", "."))
                break
        if not result["advance_required"] and re.search(r"\bаванс\b|\bпредоплат\w*", text, re.IGNORECASE):
            result["advance_required"] = True

        match = re.search(
            r"(?:оплат\w*|отсрочк\w*)[^.]{0,200}?"
            r"(?:в\s+течени[еи]|через|не\s+позднее)?\s*(\d+)\s*"
            r"(?:календарн\w*|рабоч\w*|дн\w*)",
            text,
            re.IGNORECASE,
        )
        if match:
            result["postpayment_days"] = int(match.group(1))

        for field, label in (
            ("application_security_percent", r"обеспечени\w*\s+заявк\w*"),
            ("contract_security_percent", r"обеспечени\w*\s+(?:исполнени\w*\s+)?(?:контракт\w*|договор\w*)"),
        ):
            match = re.search(label + r"[^.]{0,250}?(\d+(?:[.,]\d+)?)\s*%", text, re.IGNORECASE)
            if match:
                result[field] = float(match.group(1).replace(",", "."))
        return result

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        value = str(value or "").strip()
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%d.%m.%y %H:%M:%S", "%d.%m.%y %H:%M", "%d.%m.%y"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
            except ValueError:
                continue
        return None

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()

    @classmethod
    def _matches_keywords(cls, tender: Tender, keywords: list[str]) -> bool:
        text = cls._normalize_text(tender.full_text)
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()
