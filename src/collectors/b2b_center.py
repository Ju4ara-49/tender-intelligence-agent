"""B2B-Center collector."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from html import unescape
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector
from src.models.tender import Tender


logger = logging.getLogger(__name__)


BASE_URL = "https://www.b2b-center.ru"
SEARCH_URL = f"{BASE_URL}/market/"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


class B2BCenterCollector(BaseCollector):
    """Collector for B2B-Center."""

    # Этот идентификатор используется в config.yaml, Telegram и SQLite.
    platform = "b2b_center"

    def __init__(self, config: dict | None = None):
        self.config = config or {}

        self.max_pages = int(
            self.config.get("max_pages", 5)
        )

        self.request_delay_seconds = float(
            self.config.get("request_delay_seconds", 2)
        )

        self.timeout = int(
            self.config.get("timeout_seconds", 20)
        )

        self.session = requests.Session()

        # Реальные URL тендеров, полученные во время поиска.
        # Ключ: external_id, значение: настоящий URL процедуры.
        self._tender_urls: dict[str, str] = {}

        # Кэш названий процедур из результатов поиска.
        # Нужен как fallback, если страница деталей недоступна.
        self._tender_titles: dict[str, str] = {}

        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,image/avif,image/webp,"
                    "*/*;q=0.8"
                ),
                "Accept-Language": (
                    "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
                ),
                "Connection": "keep-alive",
            }
        )

    # ==============================================================
    # PUBLIC API
    # ==============================================================

    def search(
        self,
        keywords: list[str],
        since: datetime | None = None,
    ) -> list[Tender]:
        """Search B2B-Center by keywords."""

        results: dict[str, Tender] = {}

        for keyword in keywords:
            keyword = self._clean_text(keyword)

            if not keyword:
                continue

            logger.info(
                "B2B-Center: поиск по ключевому слову: %s",
                keyword,
            )

            try:
                html = self._load_search_page(keyword)

                found = self._parse_search_html(
                    html,
                    keyword,
                    since,
                )

                for tender in found:
                    if tender.external_id:
                        # Сохраняем настоящий URL для последующей
                        # загрузки деталей по external_id.
                        external_id = str(
                            tender.external_id
                        )

                        self._tender_urls[
                            external_id
                        ] = tender.url

                        if tender.title:
                            self._tender_titles[
                                external_id
                            ] = tender.title
                        results[tender.unique_key] = tender

            except Exception:
                logger.exception(
                    "B2B-Center: ошибка поиска по ключевому слову %s",
                    keyword,
                )

            if self.request_delay_seconds > 0:
                time.sleep(self.request_delay_seconds)

        logger.info(
            "B2B-Center: найдено %s уникальных процедур",
            len(results),
        )

        return list(results.values())

    def get_details(
        self,
        external_id: str,
    ) -> Tender | None:
        """Load tender details from B2B-Center."""

        if not external_id:
            return None

        external_id = str(external_id).strip()

        # ВАЖНО:
        # нельзя строить URL вида /market/tender-ID/.
        # B2B-Center использует реальные URL с названием процедуры.
        url = self._tender_urls.get(external_id)

        if not url:
            logger.warning(
                "B2B-Center: реальный URL для %s не найден в кэше",
                external_id,
            )

            url = self._find_tender_url_by_id(
                external_id
            )

        if not url:
            logger.error(
                "B2B-Center: не удалось найти URL тендера %s",
                external_id,
            )
            return None

        logger.info(
            "B2B-Center: загрузка деталей %s: %s",
            external_id,
            url,
        )

        try:
            response = self._get(url)

            soup = BeautifulSoup(
                response.text,
                "lxml",
            )

            text = self._clean_text(
                soup.get_text(" ", strip=True)
            )

            if not text:
                logger.warning(
                    "B2B-Center: пустая страница деталей %s",
                    external_id,
                )
                return None

            title = self._extract_detail_title(
                soup,
                external_id,
            )

            if not title:
                title = f"Тендер № {external_id}"

            # B2B-Center: detail-page values are stored in
            # dedicated table rows. Prefer structured HTML
            # over regex extraction from the whole page text.

            # ======================================================
            # B2B-Center: новая страница деталей
            # ======================================================

            # Название процедуры
            title = ""

            title_element = soup.select_one(
                "h1.trade-header-title"
            )

            if title_element is not None:
                title = self._clean_text(
                    title_element.get_text(
                        " ",
                        strip=True,
                    )
                )

            if not title:
                title = self._extract_detail_title(
                    soup,
                    external_id,
                )

            if not title:
                title = f"Тендер № {external_id}"

            # ------------------------------------------------------
            # Организатор
            # ------------------------------------------------------

            customer = ""

            organizer = soup.select_one(
                "[data-xid='organizer-information-firm-link']"
            )

            if organizer is not None:
                customer = self._clean_text(
                    organizer.get_text(
                        " ",
                        strip=True,
                    )
                )

            # ------------------------------------------------------
            # Цена
            # ------------------------------------------------------

            price = None

            price_element = soup.select_one(
                "[data-xid='total-positions-price-text']"
            )

            if price_element is not None:
                price_text = self._clean_text(
                    price_element.get_text(
                        " ",
                        strip=True,
                    )
                )

                price = self._extract_price(
                    price_text
                )

            # ------------------------------------------------------
            # Дата публикации
            # ------------------------------------------------------

            published_at = None

            published_label = soup.find(
                string=lambda s:
                s and "Опубликована" in s
            )

            if published_label is not None:
                parent = published_label.parent

                if parent is not None:
                    block = parent.parent

                    if block is not None:
                        published_text = self._clean_text(
                            block.get_text(
                                " ",
                                strip=True,
                            )
                        )

                        published_at = self._parse_date_text(
                            published_text
                        )

            # ------------------------------------------------------
            # Дедлайн
            # ------------------------------------------------------

            deadline = None

            deadline_label = soup.find(
                string=lambda s:
                s and "Окончание приёма заявок" in s
            )

            if deadline_label is not None:
                label_parent = deadline_label.parent

                if label_parent is not None:
                    container = label_parent.parent

                    if container is not None:
                        date_block = container.find_next_sibling()

                        if date_block is not None:
                            deadline_text = self._clean_text(
                                date_block.get_text(
                                    " ",
                                    strip=True,
                                )
                            )

                            deadline = self._parse_date_text(
                                deadline_text
                            )
            # ------------------------------------------------------
            # Адрес / регион поставки
            # ------------------------------------------------------

            delivery_address = ""

            address_element = soup.select_one(
                "[data-xid='delivery-widget-delivery-address']"
            )

            if address_element is not None:
                delivery_address = self._clean_text(
                    address_element.get_text(
                        " ",
                        strip=True,
                    )
                )
            # Регион сначала определяем из адреса поставки.
            region = ""

            if delivery_address:
                region = self._extract_region(
                    delivery_address
                )


            # ==========================================================
            # FINAL FALLBACK FOR B2B-CENTER OLD /market/ TEMPLATE
            # ==========================================================

            if not customer:
                organizer_row = soup.select_one(
                    "#trade-info-organizer-name"
                )

                if organizer_row is not None:
                    cells = organizer_row.select("td")

                    if len(cells) >= 2:
                        customer = self._clean_text(
                            cells[1].get_text(
                                " ",
                                strip=True,
                            )
                        )

            if published_at is None:
                published_row = soup.select_one(
                    "#trade_info_date_begin"
                )

                if published_row is not None:
                    published_at = self._parse_date_text(
                        self._clean_text(
                            published_row.get_text(
                                " ",
                                strip=True,
                            )
                        )
                    )

            if deadline is None:
                deadline_row = soup.select_one(
                    "#trade_info_date_end"
                )

                if deadline_row is not None:
                    deadline = self._parse_date_text(
                        self._clean_text(
                            deadline_row.get_text(
                                " ",
                                strip=True,
                            )
                        )
                    )

            procurement_method = (
                self._extract_procurement_method(text)
            )

            if not region:
                region = self._extract_region(text)
            commercial = self._extract_commercial_conditions(text)
            status = self._extract_status(text)

            return Tender(
                platform=self.platform,
                external_id=external_id,
                title=title[:1000],
                url=url,
                description=text[:10000],
                price=price,
                currency="RUB",
                published_at=published_at,
                deadline=deadline,
                end_date=deadline,
                customer=customer[:1000],
                region=region,
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
                    "details_loaded": True,
                    "source_url": url,
                    "procurement_method": procurement_method,
                    "status": status,
                    "commercial_conditions": commercial,
                    "search_text": text[:10000],
                },
            )

        except Exception:
            logger.exception(
                "B2B-Center: ошибка получения деталей %s",
                external_id,
            )

            fallback_title = self._tender_titles.get(
                str(external_id),
                "",
            )

            if fallback_title:
                logger.warning(
                    "B2B-Center: используем название из поиска для %s: %s",
                    external_id,
                    fallback_title,
                )

                return Tender(
                    platform=self.platform,
                    external_id=external_id,
                    title=fallback_title[:1000],
                    url=url,
                    description="",
                    price=None,
                    currency="RUB",
                    published_at=None,
                    deadline=None,
                    end_date=None,
                    customer="",
                    region="",
                    advance_required=False,
                    advance_percent=None,
                    postpayment_days=None,
                    application_security_percent=None,
                    contract_security_percent=None,
                    raw_data={
                        "details_loaded": False,
                        "details_error": True,
                        "source_url": url,
                        "search_title": fallback_title,
                    },
                )

            return None

    # ==============================================================
    # FIND TENDER URL
    # ==============================================================

    def _find_tender_url_by_id(
        self,
        external_id: str,
    ) -> str | None:
        """
        Найти настоящий URL процедуры по ID.

        Используется только если тендер был передан в get_details()
        без предварительного вызова search().
        """

        try:
            response = self._get(
                SEARCH_URL,
                params={
                    "search": external_id,
                },
            )

            soup = BeautifulSoup(
                response.text,
                "lxml",
            )

            # Сначала ищем ссылки, содержащие нужный ID.
            for link in soup.select(
                "a[href*='tender-']"
            ):
                href = self._clean_text(
                    link.get("href", "")
                )

                if not href:
                    continue

                if (
                    f"tender-{external_id}"
                    not in href
                ):
                    continue

                url = urljoin(
                    BASE_URL,
                    unescape(href),
                )

                self._tender_urls[
                    external_id
                ] = url

                logger.info(
                    "B2B-Center: URL найден по ID %s: %s",
                    external_id,
                    url,
                )

                return url

            # Запасной вариант — разобрать таблицу поиска.
            table = soup.select_one(
                "table.search-results"
            )

            if table is not None:
                for row in table.select(
                    "tbody tr"
                ):
                    link = row.select_one(
                        "a[href]"
                    )

                    if link is None:
                        continue

                    href = self._clean_text(
                        link.get("href", "")
                    )

                    if (
                        f"tender-{external_id}"
                        not in href
                    ):
                        continue

                    url = urljoin(
                        BASE_URL,
                        unescape(href),
                    )

                    self._tender_urls[
                        external_id
                    ] = url

                    return url

        except Exception:
            logger.exception(
                "B2B-Center: ошибка поиска URL по ID %s",
                external_id,
            )

        return None

    # ==============================================================
    # SEARCH HTTP
    # ==============================================================

    def _load_search_page(
        self,
        keyword: str,
    ) -> str:
        """Load first search page."""

        response = self._get(
            SEARCH_URL,
            params={
                "f_keyword": keyword,
                "searching": "1",
            }
        )

        return response.text

    # ==============================================================
    # SEARCH PARSER
    # ==============================================================

    def _parse_search_html(
        self,
        html: str,
        keyword: str,
        since: datetime | None = None,
    ) -> list[Tender]:
        """Parse B2B-Center search HTML."""

        soup = BeautifulSoup(
            html,
            "lxml",
        )

        table = soup.select_one(
            "table.search-results"
        )

        if table is None:
            logger.warning(
                "B2B-Center: таблица search-results не найдена"
            )
            return []

        rows = table.select(
            "tbody tr"
        )

        logger.info(
            "B2B-Center: найдено строк в таблице: %s",
            len(rows),
        )

        results: list[Tender] = []

        for row in rows:
            tender = self._parse_search_row(
                row,
                keyword,
            )

            if tender is None:
                continue

            if (
                since is not None
                and tender.published_at is not None
            ):
                published = self._normalize_datetime(
                    tender.published_at
                )

                since_normalized = (
                    self._normalize_datetime(since)
                )

                if published < since_normalized:
                    continue

            results.append(tender)

        logger.info(
            "B2B-Center: принято %s результатов",
            len(results),
        )

        return results

    def _parse_search_row(
        self,
        row: Any,
        keyword: str,
    ) -> Tender | None:
        """Parse one B2B-Center search result row."""

        link = row.select_one(
            "a.search-results-title[href]"
        )

        if link is None:
            return None

        href = self._clean_text(
            link.get("href", "")
        )

        if not href:
            return None

        url = urljoin(
            BASE_URL,
            unescape(href),
        )

        # B2B-Center ???????? ??? ??????? ? ????????
        # ?????? ?????? search-results-title.
        # ????? ?????????? <p> ???????? ? ????????
        # ????????? ? ????? ????????? ???? ? ?????????
        # ????????? ??????. ????? ?????? ?????? ??????.
        # Полное название процедуры находится внутри
        # .search-results-title-desc и может содержать
        # подсвеченное ключевое слово в отдельном <span>.

        title_text = ""

        desc = link.select_one(
            ".search-results-title-desc"
        )

        if desc is not None:
            type_element = desc.select_one(
                ".search-results-title-type"
            )

            if type_element is not None:
                type_element.decompose()

            for child in desc.find_all("div", recursive=False):
                style = (child.get("style") or "").lower()
                if "color:#888" in style or "font-size:smaller" in style:
                    child.decompose()

            title_text = self._clean_text(
                desc.get_text(
                    " ",
                    strip=True,
                )
            )

        if not title_text:
            title_text = self._clean_text(
                link.get_text(
                    " ",
                    strip=True,
                )
            )

        external_id = self._extract_external_id(
            href,
            title_text,
        )

        if not external_id:
            logger.debug(
                "B2B-Center: не найден ID: %s",
                title_text,
            )
            return None

        title = self._clean_procedure_title(
            title_text,
            external_id,
        )

        # B2B-Center иногда дублирует описание процедуры целиком.
        words = title.split()
        if len(words) >= 6 and len(words) % 2 == 0:
            half = len(words) // 2
            if words[:half] == words[half:]:
                title = " ".join(words[:half]).strip()

        row_text = self._clean_text(
            row.get_text(
                " ",
                strip=True,
            )
        )

        cells = row.select("td")

        customer = ""
        published_at = None
        deadline = None

        if len(cells) >= 2:
            customer = self._clean_text(
                cells[1].get_text(
                    " ",
                    strip=True,
                )
            )

        if len(cells) >= 3:
            published_at = self._parse_date_text(
                self._clean_text(
                    cells[2].get_text(
                        " ",
                        strip=True,
                    )
                )
            )

        if len(cells) >= 4:
            deadline = self._parse_date_text(
                self._clean_text(
                    cells[3].get_text(
                        " ",
                        strip=True,
                    )
                )
            )
        price = self._extract_price(
            row_text
        )

        procurement_method = (
            self._extract_procurement_method(
                row_text
            )
        )

        return Tender(
            platform=self.platform,
            external_id=str(external_id),
            title=title[:1000],
            url=url,
            description=row_text[:10000],
            price=price,
            currency="RUB",
            published_at=published_at,
            deadline=deadline,
            end_date=deadline,
            customer=customer[:1000],
            raw_data={
                "keyword": keyword,
                "search_text": row_text[:10000],
                "search_href": href,
                "details_url": url,
                "procurement_method": procurement_method,
            },
        )

    # ==============================================================
    # EXTRACTORS
    # ==============================================================

    @staticmethod
    def _extract_external_id(
        href: str,
        text: str,
    ) -> str | None:
        """Extract B2B-Center tender ID."""

        for source in (
            href,
            text,
        ):
            source = unescape(
                str(source or "")
            )

            patterns = [
                r"/tenders?-(\d+)",
                r"\bТендер\s*№\s*(\d+)\b",
                r"\b(?:Запрос предложений|Аукцион|Конкурс)\s*№\s*(\d+)\b",
            ]

            for pattern in patterns:
                match = re.search(
                    pattern,
                    source,
                    flags=re.IGNORECASE,
                )

                if match:
                    return match.group(1)

        return None

    @staticmethod
    def _extract_procedure_title(
        row: Any,
        title_text: str,
        row_text: str,
    ) -> str:
        """Extract human-readable procedure title."""

        if title_text:
            value = re.sub(
                r"^\s*(?:Тендер|Запрос предложений|"
                r"Аукцион|Конкурс)\s*№\s*\d+\s*",
                "",
                title_text,
                flags=re.IGNORECASE,
            ).strip()

            if value:
                return value

        for link in row.select("a[href]"):
            value = B2BCenterCollector._clean_text(
                link.get_text(
                    " ",
                    strip=True,
                )
            )

            if not value:
                continue

            if re.search(
                r"(?:Тендер|Запрос предложений|Аукцион|Конкурс)\s*№",
                value,
                flags=re.IGNORECASE,
            ):
                value = re.sub(
                    r"^\s*(?:Тендер|Запрос предложений|"
                    r"Аукцион|Конкурс)\s*№\s*\d+\s*",
                    "",
                    value,
                    flags=re.IGNORECASE,
                ).strip()

                if value:
                    return value

        return row_text[:1000]

    @staticmethod
    def _extract_labeled_value(
        text: str,
        labels: list[str],
    ) -> str:
        for label in labels:
            pattern = (
                re.escape(label)
                + r"\s*[:\-]?\s*"
                + r"(.{2,500}?)"
                + r"(?=\s+(?:Опубликовано|"
                r"Актуально до|Дата|НМЦ|Цена|"
                r"Место|Регион)\b|$)"
            )

            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                return B2BCenterCollector._clean_text(
                    match.group(1)
                )[:1000]

        return ""

    @staticmethod
    def _extract_price(
        text: str,
    ) -> float | None:

        patterns = [
            r"(?:НМЦК|Начальная цена|Цена|Сумма)"
            r".{0,100}?"
            r"([\d\s\u00a0]+(?:[,.]\d{1,2})?)"
            r"\s*(?:₽|руб\.?|рублей)",
            r"([\d\s\u00a0]+(?:[,.]\d{1,2})?)"
            r"\s*(?:₽|руб\.?|рублей)",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            try:
                value = (
                    match.group(1)
                    .replace(" ", "")
                    .replace("\u00a0", "")
                    .replace(",", ".")
                )

                result = float(value)

                if result > 0:
                    return result

            except (
                TypeError,
                ValueError,
            ):
                continue

        return None

    @staticmethod
    def _parse_date_text(
        text: str,
    ) -> datetime | None:

        if not text:
            return None

        patterns = [
            r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})",
            r"(\d{2}\.\d{2}\.\d{4})",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
            )

            if not match:
                continue

            date_value = match.group(1)

            time_value = (
                match.group(2)
                if match.lastindex and match.lastindex >= 2
                else "00:00"
            )

            try:
                dt = datetime.strptime(
                    f"{date_value} {time_value}",
                    "%d.%m.%Y %H:%M",
                )

                return dt.replace(tzinfo=MOSCOW_TZ).astimezone(timezone.utc)

            except ValueError:
                continue

        return None

    @staticmethod
    def _extract_date(
        text: str,
        labels: list[str],
    ) -> datetime | None:

        for label in labels:
            pattern = (
                re.escape(label)
                + r"\s*[:\-]?\s*"
                + r"(\d{2}\.\d{2}\.\d{4})"
                + r"(?:\s+(\d{2}:\d{2}))?"
            )

            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            try:
                dt = datetime.strptime(
                    (
                        f"{match.group(1)} "
                        f"{match.group(2) or '00:00'}"
                    ),
                    "%d.%m.%Y %H:%M",
                )

                return dt.replace(tzinfo=MOSCOW_TZ).astimezone(timezone.utc)

            except ValueError:
                continue

        return None

    @staticmethod
    def _extract_detail_title(
        soup: BeautifulSoup,
        external_id: str,
    ) -> str:

        selectors = [
            "h1 .s2",
            "h1 span.value[itemprop='articleBody']",
            ".s2",
            ".tender-title",
            ".procedure-title",
        ]

        for selector in selectors:
            element = soup.select_one(selector)

            if element is None:
                continue

            value = B2BCenterCollector._clean_text(
                element.get_text(
                    " ",
                    strip=True,
                )
            )

            if not value:
                continue

            value = re.sub(
                r"^\s*(?:Тендер|Запрос предложений|"
                r"Аукцион|Конкурс)\s*№\s*"
                + re.escape(str(external_id)),
                "",
                value,
                flags=re.IGNORECASE,
            ).strip()

            if value:
                return value[:1000]

        return ""

    @staticmethod
    def _extract_procurement_method(
        text: str,
    ) -> str:
        """Extract procurement method from B2B-Center detail page."""

        value = B2BCenterCollector._clean_text(
            text
        )

        # На странице B2B-Center название процедуры обычно
        # находится непосредственно перед номером процедуры.
        patterns = [
            r"\b(Запрос предложений)\s+№\s*\d+",
            r"\b(Запрос котировок)\s+№\s*\d+",
            r"\b(Аукцион)\s+№\s*\d+",
            r"\b(Конкурс)\s+№\s*\d+",
            r"\b(Тендер)\s+№\s*\d+",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                value,
                flags=re.IGNORECASE,
            )

            if match:
                return match.group(1)

        return ""

    @staticmethod
    def _clean_procedure_title(
        value: str,
        external_id: str | None = None,
    ) -> str:
        """Убрать служебный тип и номер, сохранив название процедуры."""

        title = B2BCenterCollector._clean_text(value)

        title = re.sub(
            r"^\s*(?:Тендер|Запрос предложений|Аукцион|Конкурс|"
            r"Запрос цен|Мониторинг цен|Процедура закупки|"
            r"Объявление о продаже)\s*№?\s*\d+\s*[:—-]?\s*",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()

        if external_id:
            title = re.sub(
                r"\s*[—-]?\s*(?:Тендер|Запрос предложений|Аукцион|"
                r"Конкурс|Запрос цен)\s*№\s*"
                + re.escape(str(external_id))
                + r"\s*$",
                "",
                title,
                flags=re.IGNORECASE,
            ).strip()

        return title[:1000]

    @staticmethod
    def _extract_region(text: str) -> str:
        """Извлечь адрес поставки / регион из доступной карточки B2B."""

        value = B2BCenterCollector._extract_labeled_value(
            text,
            [
                "Адрес места поставки товара, проведения работ или оказания услуг",
                "Место поставки",
                "Регион поставки",
            ],
        )

        return value[:1000]

    @staticmethod
    def _extract_status(text: str) -> str:
        match = re.search(
            r"Статус объявления\s*:\s*([^.;]{2,100})",
            text,
            flags=re.IGNORECASE,
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_commercial_conditions(text: str) -> dict[str, object]:
        """Извлечь только явно опубликованные коммерческие условия."""

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
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                result["advance_required"] = True
                result["advance_percent"] = float(
                    match.group(1).replace(",", ".")
                )
                break

        if not result["advance_required"] and re.search(
            r"\bаванс\b|\bпредоплат\w*",
            text,
            flags=re.IGNORECASE,
        ):
            result["advance_required"] = True

        match = re.search(
            r"(?:оплат\w*|отсрочк\w*)[^.]{0,200}?"
            r"(?:в\s+течени[еи]|через|не\s+позднее)?\s*(\d+)\s*"
            r"(?:календарн\w*|рабоч\w*|дн\w*)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            result["postpayment_days"] = int(match.group(1))

        for field, labels in (
            (
                "application_security_percent",
                r"обеспечени\w*\s+заявк\w*",
            ),
            (
                "contract_security_percent",
                r"обеспечени\w*\s+(?:исполнени\w*\s+)?"
                r"(?:контракт\w*|договор\w*)",
            ),
        ):
            match = re.search(
                labels + r"[^.]{0,250}?(\d+(?:[.,]\d+)?)\s*%",
                text,
                flags=re.IGNORECASE,
            )
            if match:
                result[field] = float(match.group(1).replace(",", "."))

        return result

    # ==============================================================
    # HTTP / UTILS
    # ==============================================================

    def _get(
        self,
        url: str,
        params: dict | None = None,
    ) -> requests.Response:

        response = self.session.get(
            url,
            params=params,
            timeout=self.timeout,
        )

        response.raise_for_status()

        return response

    @staticmethod
    def _normalize_datetime(
        value: datetime,
    ) -> datetime:

        if value.tzinfo is None:
            return value.replace(tzinfo=MOSCOW_TZ).astimezone(timezone.utc)

        return value.astimezone(timezone.utc)

    @staticmethod
    def _clean_text(
        value: str,
    ) -> str:

        value = unescape(
            str(value or "")
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value.strip()

