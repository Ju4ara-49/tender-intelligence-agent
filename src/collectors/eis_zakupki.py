"""EIS / zakupki.gov.ru collector."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any
from urllib.parse import urljoin

import requests
import truststore
from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector
from src.models.tender import Tender


logger = logging.getLogger(__name__)

# ЕИС с июля 2026 использует отечественную сертификатную цепочку.
# truststore позволяет requests использовать хранилище сертификатов
# операционной системы Windows.
truststore.inject_into_ssl()

BASE_URL = "https://zakupki.gov.ru"
SEARCH_URL = f"{BASE_URL}/epz/order/extendedsearch/results.html"


class EisZakupkiCollector(BaseCollector):
    """Collector for EIS / zakupki.gov.ru."""

    platform = "eis"

    def __init__(self, config: dict | None = None):
        self.config = config or {}

        self.max_pages = int(
            self.config.get("max_pages", 5)
        )

        self.records_per_page = int(
            self.config.get("records_per_page", 10)
        )

        self.request_delay_seconds = float(
            self.config.get("request_delay_seconds", 1)
        )

        self.timeout = int(
            self.config.get("timeout_seconds", 10)
        )

        self.lookback_days = int(
            self.config.get("lookback_days", 3)
        )

        self.session = requests.Session()

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

    # ==================================================================
    # PUBLIC API
    # ==================================================================

    def search(
        self,
        keywords: list[str],
        since: datetime | None = None,
    ) -> list[Tender]:
        """Ищет закупки по ключевым словам и дедуплицирует результаты."""

        results: dict[str, Tender] = {}

        effective_since = since

        if effective_since is None and self.lookback_days > 0:
            effective_since = (
                datetime.now(timezone.utc)
                - timedelta(days=self.lookback_days)
            )

        for keyword in keywords:
            keyword = self._clean_text(keyword)

            if not keyword:
                continue

            logger.info(
                "ЕИС: поиск по ключевому слову: %s",
                keyword,
            )

            try:
                found = self._search_keyword(
                    keyword,
                    effective_since,
                )

                for tender in found:
                    if tender.external_id:
                        results[tender.unique_key] = tender

            except Exception:
                logger.exception(
                    "ЕИС: ошибка поиска по ключевому слову %s",
                    keyword,
                )

            if self.request_delay_seconds > 0:
                time.sleep(self.request_delay_seconds)

        logger.info(
            "ЕИС: итог поиска: %s уникальных закупок",
            len(results),
        )

        return list(results.values())

    def get_details(
        self,
        external_id: str,
    ) -> Tender | None:
        """Получает подробности закупки по регистрационному номеру."""

        if not external_id:
            return None

        urls = [
            (
                f"{BASE_URL}/epz/order/notice/ea20/view/"
                f"common-info.html?regNumber={external_id}"
            ),
            (
                f"{BASE_URL}/epz/order/notice/ea44/view/"
                f"common-info.html?regNumber={external_id}"
            ),
            (
                f"{BASE_URL}/epz/order/notice/notice223/"
                f"common-info.html?regNumber={external_id}"
            ),
        ]

        last_error = None

        for url in urls:
            try:
                response = self._get(url)

                if response.status_code == 404:
                    logger.debug(
                        "ЕИС: URL деталей не найден: %s",
                        url,
                    )
                    continue

                if self._has_captcha(response.text):
                    logger.warning(
                        "ЕИС: CAPTCHA на странице деталей %s",
                        external_id,
                    )
                    return None

                soup = BeautifulSoup(
                    response.text,
                    "lxml",
                )

                parsed = self._parse_details_page(
                    soup,
                    external_id,
                    url,
                )

                if parsed is not None:
                    return parsed

            except requests.HTTPError as exc:
                last_error = exc

                if (
                    getattr(exc.response, "status_code", None)
                    == 404
                ):
                    continue

                logger.exception(
                    "ЕИС: HTTP ошибка получения деталей %s",
                    external_id,
                )
                return None

            except Exception as exc:
                last_error = exc

                logger.exception(
                    "ЕИС: ошибка получения деталей %s",
                    external_id,
                )
                return None

        logger.warning(
            "ЕИС: не удалось получить детали %s | error=%s",
            external_id,
            last_error,
        )

        return None

    # ==================================================================
    # SEARCH
    # ==================================================================

    def _search_keyword(
        self,
        keyword: str,
        since: datetime | None,
    ) -> list[Tender]:

        results: list[Tender] = []

        for page in range(
            1,
            self.max_pages + 1,
        ):
            params = {
                "searchString": keyword,
                "morphology": "on",
                "pageNumber": page,
                "sortDirection": "false",
                "recordsPerPage": f"_{self.records_per_page}",
                "showLotsInfoHidden": "false",
                "sortBy": "UPDATE_DATE",
                "fz44": "on",
                "fz223": "on",
                "af": "on",
                "ca": "on",
                "pc": "on",
                "pa": "on",
                "currencyIdGeneral": "-1",
            }

            logger.info(
                "ЕИС: запрос keyword=%s page=%s",
                keyword,
                page,
            )

            try:
                response = self._get(
                    SEARCH_URL,
                    params=params,
                )

            except Exception:
                logger.exception(
                    "ЕИС: HTTP ошибка page=%s keyword=%s",
                    page,
                    keyword,
                )
                break

            if self._has_captcha(response.text):
                logger.warning(
                    "ЕИС: обнаружена CAPTCHA, поиск остановлен",
                )
                break

            soup = BeautifulSoup(
                response.text,
                "lxml",
            )

            # Актуальная структура ЕИС 2026:
            #
            # <div class="registry-entry__form">
            #
            # Старый selector search-registry-entry-block больше
            # не используется текущей страницей результатов.
            blocks = soup.select(
                "div.registry-entry__form"
            )

            if not blocks:
                # Запасной вариант на случай очередного изменения
                # HTML-разметки ЕИС.
                blocks = soup.select(
                    "div[class*='registry-entry__form']"
                )

            if not blocks:
                logger.info(
                    "ЕИС: страница %s не содержит карточек "
                    "для keyword=%s",
                    page,
                    keyword,
                )
                break

            logger.info(
                "ЕИС: страница %s содержит %s карточек",
                page,
                len(blocks),
            )

            page_count = 0

            for block in blocks:
                tender = self._parse_search_block(
                    block,
                    keyword,
                )

                if tender is None:
                    continue

                if (
                    since is not None
                    and tender.published_at is not None
                ):
                    tender_date = self._normalize_datetime(
                        tender.published_at
                    )

                    since_date = self._normalize_datetime(
                        since
                    )

                    if tender_date < since_date:
                        continue

                search_text = tender.raw_data.get(
                    "search_text",
                    "",
                )

                if self._is_finished_procedure(
                    search_text
                ):
                    logger.debug(
                        "ЕИС: пропущена завершённая закупка %s",
                        tender.external_id,
                    )
                    continue

                results.append(tender)
                page_count += 1

            logger.info(
                "ЕИС: страница %s: принято %s результатов",
                page,
                page_count,
            )

            if len(blocks) < self.records_per_page:
                break

            if self.request_delay_seconds > 0:
                time.sleep(self.request_delay_seconds)

        return results

    # ==================================================================
    # SEARCH BLOCK PARSER
    # ==================================================================

    def _parse_search_block(
        self,
        block: Any,
        keyword: str,
    ) -> Tender | None:

        text = self._clean_text(
            block.get_text(
                " ",
                strip=True,
            )
        )

        if not text:
            return None

        links = block.select("a[href]")

        notice_href = ""

        # В актуальной ЕИС номер закупки находится в:
        #
        # .registry-entry__header-mid__number a
        #
        # Но сохраняем общий поиск ссылки для устойчивости.
        number_links = block.select(
            ".registry-entry__header-mid__number a[href]"
        )

        candidate_links = (
            number_links
            if number_links
            else links
        )

        for link in candidate_links:
            href = str(
                link.get("href", "")
            ).strip()

            if not href:
                continue

            if (
                "regNumber=" in href
                or "/epz/order/notice/" in href
                or "/223/purchase/public/purchase/" in href
            ):
                notice_href = href
                break

        if not notice_href:
            # Последняя попытка: ищем номер непосредственно
            # в блоке, если ссылка изменилась.
            external_id = self._extract_reg_number(
                "",
                text,
            )
        else:
            external_id = self._extract_reg_number(
                notice_href,
                text,
            )

        if not external_id:
            logger.debug(
                "ЕИС: не найден номер закупки: %s",
                text[:500],
            )
            return None

        if notice_href:
            notice_url = urljoin(
                BASE_URL,
                unescape(notice_href),
            )
        else:
            notice_url = ""

        detail_url = self._build_detail_url(
            external_id,
            notice_url,
            text,
        )

        law_type = self._extract_law_type(
            text
        )

        title = self._extract_object_from_block(
            block
        )

        if not title:
            title = self._extract_object_from_text(
                text
            )

        if not title:
            title = self._extract_title_from_block(
                block
            )

        if not title:
            title = f"Закупка {external_id}"

        price = self._extract_price(
            block
        )

        customer = self._extract_customer(
            block
        )

        if not customer:
            customer = self._extract_customer_from_text(
                text
            )

        published_at = self._parse_date_from_block(
            block
        )

        start_date, end_date = (
            self._extract_procedure_dates(
                text
            )
        )

        region = self._extract_region(
            block
        )

        if not region:
            region = self._extract_region_from_text(
                text
            )

        procurement_method = (
            self._extract_procurement_method(
                text
            )
        )

        status = self._extract_status(
            text
        )

        logger.debug(
            "ЕИС: parsed external_id=%s | title=%s | "
            "price=%s | customer=%s",
            external_id,
            title[:100],
            price,
            customer[:100],
        )

        return Tender(
            platform=self.platform,
            external_id=external_id,
            title=title[:1000],
            url=detail_url,
            description=title[:10000],
            price=price,
            currency="RUB",
            start_date=start_date,
            end_date=end_date,
            deadline=end_date,
            published_at=published_at,
            region=region,
            customer=customer,
            law_type=law_type,
            raw_data={
                "keyword": keyword,
                "law_type": law_type,
                "search_text": text[:10000],
                "search_href": notice_href,
                "details_url": detail_url,
                "procurement_method": procurement_method,
                "status": status,
            },
        )

    # ==================================================================
    # DETAILS PARSER
    # ==================================================================

    def _parse_details_page(
        self,
        soup: BeautifulSoup,
        external_id: str,
        url: str,
    ) -> Tender | None:

        text = self._clean_text(
            soup.get_text(
                " ",
                strip=True,
            )
        )

        if not text:
            return None

        law_type = self._extract_law_type(
            text
        )

        title = self._extract_labeled_value(
            text,
            [
                "Объект закупки",
                "Наименование объекта закупки",
            ],
        )

        if not title:
            title = self._extract_between(
                text,
                "Объект закупки",
                "Организация, осуществляющая размещение",
            )

        if not title:
            title = self._extract_between(
                text,
                "Объект закупки",
                "Заказчик",
            )

        customer = self._extract_customer_from_soup(
            soup
        )

        if not customer:
            customer = self._extract_customer_from_text(
                text
            )

        price = self._extract_detail_price(
            text
        )

        published_at = self._extract_detail_datetime(
            text,
            [
                "Размещено",
                "Дата размещения",
                "Дата публикации",
                "Опубликовано",
            ],
        )

        start_date, end_date = (
            self._extract_procedure_dates(
                text
            )
        )

        region = ""

        # ? ??????? ??? ?????? ????????? ?????:
        # "??????" ? "?????????? ? ????????? ???????".
        # ?????????? Unicode-escape, ????? ?? ???????? ?? ?????????
        # ????????? ?????.

        region_marker = "\u0420\u0435\u0433\u0438\u043e\u043d"
        region_end_marker = (
            "\u0418\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u044f "
            "\u043e \u043f\u0440\u043e\u0446\u0435\u0434\u0443\u0440\u0435 "
            "\u0437\u0430\u043a\u0443\u043f\u043a\u0438"
        )

        region_start = text.find(region_marker)

        if region_start >= 0:
            value_start = (
                region_start
                + len(region_marker)
            )

            region_end = text.find(
                region_end_marker,
                value_start,
            )

            if region_end >= 0:
                region = self._clean_text(
                    text[value_start:region_end]
                )

            if len(region) > 100:
                region = ""

        if not region:
            region = self._extract_region_from_soup(
                soup
            )

        if not region:
            region = self._extract_region_from_text(
                text
            )

        procurement_method = (
            self._extract_procurement_method(
                text
            )
        )

        status = self._extract_status(
            text
        )

        if not title:
            title = f"Закупка {external_id}"

        description = self._extract_description(
            text
        )

        return Tender(
            platform=self.platform,
            external_id=external_id,
            title=title[:1000],
            url=url,
            description=description[:10000],
            price=price,
            currency="RUB",
            start_date=start_date,
            end_date=end_date,
            deadline=end_date,
            published_at=published_at,
            region=region,
            customer=customer,
            law_type=law_type,
            raw_data={
                "details_loaded": True,
                "source_url": url,
                "procurement_method": procurement_method,
                "status": status,
            },
        )

    # ==================================================================
    # REGISTRATION NUMBER
    # ==================================================================

    @staticmethod
    def _extract_reg_number(
        href: str,
        text: str,
    ) -> str | None:

        href = unescape(
            str(href or "")
        )

        text = unescape(
            str(text or "")
        )

        patterns = [
            r"[?&]regNumber=(\d{10,30})",
            r"[?&]purchaseNoticeNumber=(\d{10,30})",
            r"regNumber\s*=\s*[\"']?(\d{10,30})",
            r"\b№\s*(\d{10,30})\b",
            r"\b(\d{19})\b",
        ]

        for source in (
            href,
            text,
        ):
            for pattern in patterns:
                match = re.search(
                    pattern,
                    source,
                    flags=re.IGNORECASE,
                )

                if match:
                    return match.group(1)

        return None

    # ==================================================================
    # DETAIL URL
    # ==================================================================

    @staticmethod
    def _build_detail_url(
        external_id: str,
        original_url: str,
        text: str = "",
    ) -> str:

        if original_url:
            if (
                "zakupki.gov.ru" in original_url
                and (
                    "regNumber=" in original_url
                    or "purchase/public/purchase/" in original_url
                )
            ):
                return original_url

        # Для 223-ФЗ стараемся определить старую
        # публичную структуру из текста.
        if "223-ФЗ" in text:
            return (
                f"{BASE_URL}/223/purchase/public/purchase/"
                f"info/common-info.html?regNumber={external_id}"
            )

        return (
            f"{BASE_URL}/epz/order/notice/ea20/view/"
            f"common-info.html?regNumber={external_id}"
        )

    # ==================================================================
    # COMMERCIAL CONDITIONS
    # ==================================================================

    @staticmethod
    def _extract_commercial_conditions(
        text: str,
    ) -> dict[str, object]:

        text = str(text or "")

        result: dict[str, object] = {
            "advance_required": False,
            "advance_percent": None,
            "postpayment_days": None,
            "application_security_percent": None,
            "contract_security_percent": None,
        }

        # --------------------------------------------------------------
        # АВАНС
        # --------------------------------------------------------------

        advance_patterns = [
            r"аванс(?:овый платеж)?[^.]{0,250}?(\d+(?:[.,]\d+)?)\s*%",
            r"предоплат[аы][^.]{0,250}?(\d+(?:[.,]\d+)?)\s*%",
            r"предварительн(?:ая|ой)\s+оплат[аы][^.]{0,250}?(\d+(?:[.,]\d+)?)\s*%",
        ]

        for pattern in advance_patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                try:
                    result["advance_percent"] = float(
                        match.group(1).replace(",", ".")
                    )
                    result["advance_required"] = True
                except (TypeError, ValueError):
                    pass
                break

        if not result["advance_required"]:
            if re.search(
                r"\bаванс\b|\bпредоплат[аы]\b|\bпредварительн\w+\s+оплат",
                text,
                flags=re.IGNORECASE,
            ):
                result["advance_required"] = True

        # --------------------------------------------------------------
        # ОТСРОЧКА / СРОК ОПЛАТЫ
        # --------------------------------------------------------------

        postpayment_patterns = [
            r"оплат[аы][^.]{0,250}?(?:через|в течение|не позднее)\s*(\d+)\s*(?:календарн\w*|рабоч\w*|дн\w*)",
            r"отсрочк[аи][^.]{0,150}?(\d+)\s*(?:календарн\w*|рабоч\w*|дн\w*)",
            r"(\d+)\s*(?:календарн\w*|рабоч\w*|дн\w*)[^.]{0,150}?после\s+(?:поставки|приемки|подписания)",
        ]

        for pattern in postpayment_patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                try:
                    result["postpayment_days"] = int(
                        match.group(1)
                    )
                except (TypeError, ValueError):
                    pass
                break

        # --------------------------------------------------------------
        # ОБЕСПЕЧЕНИЕ ЗАЯВКИ
        # --------------------------------------------------------------

        application_patterns = [
            r"обеспечени[ея]\s+(?:заявки|заявления)[^.]{0,300}?(\d+(?:[.,]\d+)?)\s*%",
            r"размер\s+обеспечения\s+(?:заявки|заявления)[^.]{0,300}?(\d+(?:[.,]\d+)?)\s*%",
        ]

        for pattern in application_patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                try:
                    result["application_security_percent"] = float(
                        match.group(1).replace(",", ".")
                    )
                except (TypeError, ValueError):
                    pass
                break

        # --------------------------------------------------------------
        # ОБЕСПЕЧЕНИЕ КОНТРАКТА
        # --------------------------------------------------------------

        contract_patterns = [
            r"обеспечени[ея]\s+(?:исполнения|исполнение)\s+(?:контракта|договора)[^.]{0,300}?(\d+(?:[.,]\d+)?)\s*%",
            r"размер\s+обеспечения\s+(?:исполнения|исполнение)\s+(?:контракта|договора)[^.]{0,300}?(\d+(?:[.,]\d+)?)\s*%",
        ]

        for pattern in contract_patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                try:
                    result["contract_security_percent"] = float(
                        match.group(1).replace(",", ".")
                    )
                except (TypeError, ValueError):
                    pass
                break

        return result
    # ==================================================================
    # LAW
    # ==================================================================

    @staticmethod
    def _extract_law_type(
        text: str,
    ) -> str:

        text = str(text or "")

        if re.search(
            r"\b44\s*[-]?\s*ФЗ\b",
            text,
            flags=re.IGNORECASE,
        ):
            return "44-ФЗ"

        if re.search(
            r"\b223\s*[-]?\s*ФЗ\b",
            text,
            flags=re.IGNORECASE,
        ):
            return "223-ФЗ"

        return ""

    # ==================================================================
    # OBJECT / TITLE
    # ==================================================================

    @staticmethod
    def _extract_object_from_block(
        block: Any,
    ) -> str:

        # На текущей странице ЕИС значение объекта закупки
        # находится в registry-entry__body-value.
        titles = block.select(
            ".registry-entry__body-title"
        )

        values = block.select(
            ".registry-entry__body-value"
        )

        for title, value in zip(
            titles,
            values,
        ):
            title_text = (
                EisZakupkiCollector._clean_text(
                    title.get_text(
                        " ",
                        strip=True,
                    )
                )
            )

            if "Объект закупки" not in title_text:
                continue

            result = (
                EisZakupkiCollector._clean_text(
                    value.get_text(
                        " ",
                        strip=True,
                    )
                )
            )

            if result:
                return result[:1000]

        return ""

    @staticmethod
    def _extract_object_from_text(
        text: str,
    ) -> str:

        text = str(text or "")

        patterns = [
            (
                r"Объект закупки\s+"
                r"(.+?)\s+"
                r"(?:Заказчик|Организация, осуществляющая размещение)"
            ),
            (
                r"Объект закупки\s+"
                r"(.+?)\s+"
                r"Начальная цена"
            ),
            (
                r"Наименование объекта закупки\s+"
                r"(.+?)\s+"
                r"(?:Этап закупки|Начальная цена)"
            ),
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            value = re.sub(
                r"\s+",
                " ",
                match.group(1),
            ).strip()

            if len(value) >= 5:
                return value[:1000]

        return ""

    @staticmethod
    def _extract_title_from_block(
        block: Any,
    ) -> str:

        selectors = [
            ".registry-entry__header-mid__title",
            ".registry-entry__header-top__title",
            ".registry-entry__body-value",
        ]

        ignored = {
            "Электронный аукцион",
            "Запрос котировок в электронной форме",
            "Открытый конкурс",
            "Конкурс в электронной форме",
            "Иной способ",
            "Конкурс",
            "Аукцион",
            "Подача заявок",
            "Работа комиссии",
        }

        for selector in selectors:
            for element in block.select(
                selector
            ):
                value = (
                    EisZakupkiCollector._clean_text(
                        element.get_text(
                            " ",
                            strip=True,
                        )
                    )
                )

                if not value:
                    continue

                if value in ignored:
                    continue

                if len(value) >= 10:
                    return value[:1000]

        return ""

    # ==================================================================
    # CUSTOMER / REGION FROM DETAILS HTML
    # ==================================================================

    @staticmethod
    def _extract_customer_from_soup(
        soup: BeautifulSoup,
    ) -> str:

        # В карточке ЕИС фактический заказчик находится
        # в td.tableBlock__col_header.
        #
        # Пример:
        # ГОСУДАРСТВЕННОЕ БЮДЖЕТНОЕ УЧРЕЖДЕНИЕ РЕСПУБЛИКИ МАРИЙ ЭЛ
        # "РЕСПУБЛИКАНСКАЯ КЛИНИЧЕСКАЯ БОЛЬНИЦА"
        #
        # Не используем regex по всей странице:
        # в шапке ЕИС встречается много служебных организаций.

        legal_prefixes = (
            "ГОСУДАРСТВЕННОЕ ",
            "МУНИЦИПАЛЬНОЕ ",
            "ФЕДЕРАЛЬНОЕ ",
            "БЮДЖЕТНОЕ ",
            "КАЗЕННОЕ ",
            "АВТОНОМНОЕ ",
            "ОБЛАСТНОЕ ",
            "КРАЕВОЕ ",
            "РЕСПУБЛИКАНСКОЕ ",
            "МУНИЦИПАЛЬНОЕ ",
        )

        seen = set()

        selectors = [
            "td.tableBlock__col_header",
            ".tableBlock__col_header",
        ]

        for selector in selectors:
            for element in soup.select(selector):
                value = EisZakupkiCollector._clean_text(
                    element.get_text(
                        " ",
                        strip=True,
                    )
                )

                if not value:
                    continue

                if value in seen:
                    continue

                seen.add(value)

                if len(value) < 10 or len(value) > 1000:
                    continue

                upper = value.upper()

                if any(
                    upper.startswith(prefix)
                    for prefix in legal_prefixes
                ):
                    return value[:1000]

        return ""
    @staticmethod
    def _extract_region_from_soup(
        soup: BeautifulSoup,
    ) -> str:

        text = EisZakupkiCollector._clean_text(
            soup.get_text(
                " ",
                strip=True,
            )
        )

        if not text:
            return ""

        # ? ?????????? ???????? ??? ???? ?????? ???????????:
        #
        # ?????? ????? ?? ???? ?????????? ? ????????? ???????
        #
        # ????? ???????? ?????? ????? ????? ????? ?????????.

        marker_start = "??????"
        marker_end = "?????????? ? ????????? ???????"

        search_position = 0

        while True:
            start_position = text.find(
                marker_start,
                search_position,
            )

            if start_position < 0:
                break

            value_start = (
                start_position
                + len(marker_start)
            )

            end_position = text.find(
                marker_end,
                value_start,
            )

            if end_position < 0:
                break

            value = text[
                value_start:end_position
            ]

            value = EisZakupkiCollector._clean_text(
                value
            )

            # ?????? ?????? ???? ???????? ?????????,
            # ? ?? ??????? ??? ?????? ?????? ????????.
            if value:
                if len(value) <= 100:
                    if "????? ????????" not in value:
                        if "???????????" not in value:
                            return value[:200]

            search_position = (
                start_position
                + len(marker_start)
            )

        return ""


    # ==================================================================
    # CUSTOMER
    # ==================================================================

    @staticmethod
    def _extract_customer_from_soup(
        soup: BeautifulSoup,
    ) -> str:

        # В актуальной карточке ЕИС заказчик присутствует
        # в td.tableBlock__col_header.
        #
        # Пример:
        # ГОСУДАРСТВЕННОЕ БЮДЖЕТНОЕ УЧРЕЖДЕНИЕ ...
        #
        # Берём только организации, а не служебные заголовки
        # таблицы характеристик.

        organization_prefixes = (
            "ГОСУДАРСТВЕННОЕ ",
            "МУНИЦИПАЛЬНОЕ ",
            "ФЕДЕРАЛЬНОЕ ",
            "БЮДЖЕТНОЕ ",
            "АВТОНОМНОЕ ",
            "КАЗЕННОЕ ",
            "ОБЛАСТНОЕ ",
            "КРАЕВОЕ ",
            "РЕСПУБЛИКАНСКОЕ ",
            "МУНИЦИПАЛЬНОЕ ",
            "ООО ",
            "АО ",
            "ПАО ",
            "ОАО ",
            "ЗАО ",
            "ИП ",
        )

        selectors = [
            "td.tableBlock__col_header",
            ".tableBlock__col_header",
        ]

        seen = set()

        for selector in selectors:
            for element in soup.select(selector):
                value = EisZakupkiCollector._clean_text(
                    element.get_text(
                        " ",
                        strip=True,
                    )
                )

                if not value:
                    continue

                if value in seen:
                    continue

                seen.add(value)

                if len(value) < 10 or len(value) > 1000:
                    continue

                upper_value = value.upper()

                if any(
                    upper_value.startswith(prefix)
                    for prefix in organization_prefixes
                ):
                    # Исключаем очевидные заголовки таблиц.
                    if (
                        "НАИМЕНОВАНИЕ ХАРАКТЕРИСТИКИ"
                        in upper_value
                    ):
                        continue

                    if (
                        "ЗНАЧЕНИЕ ХАРАКТЕРИСТИКИ"
                        in upper_value
                    ):
                        continue

                    if (
                        "ЕДИНИЦА ИЗМЕРЕНИЯ"
                        in upper_value
                    ):
                        continue

                    return value[:1000]

        return ""
    @staticmethod
    def _extract_customer(
        block: Any,
    ) -> str:

        titles = block.select(
            ".registry-entry__body-title"
        )

        values = block.select(
            ".registry-entry__body-value"
        )

        for title, value in zip(
            titles,
            values,
        ):
            title_text = (
                EisZakupkiCollector._clean_text(
                    title.get_text(
                        " ",
                        strip=True,
                    )
                )
            )

            if (
                "Заказчик" in title_text
                or "Организация" in title_text
            ):
                result = (
                    EisZakupkiCollector._clean_text(
                        value.get_text(
                            " ",
                            strip=True,
                        )
                    )
                )

                if result:
                    return result[:1000]

        return ""

    @staticmethod
    def _extract_customer_from_text(
        text: str,
    ) -> str:

        text = str(text or "")

        # В деталях ЕИС организация, размещающая закупку,
        # и фактический заказчик могут быть разными.
        # Поэтому сначала ищем именно "Заказчик", а не
        # "Организация, осуществляющая размещение".

        patterns = [
            (
                r"(?:^|\s)Заказчик\s*[:\-]?\s*"
                r"(.+?)\s+"
                r"(?:Место нахождения|Почтовый адрес|"
                r"Адрес электронной почты|Контактный телефон|"
                r"Ответственное должностное лицо|"
                r"Начальная цена|НМЦК|Регион)"
            ),
            (
                r"Заказчик\s*[:\-]?\s*"
                r"(.+?)\s+"
                r"(?:Место нахождения|Почтовый адрес|"
                r"Адрес электронной почты|"
                r"Ответственное должностное лицо)"
            ),
            (
                r"Организация, осуществляющая размещение\s+"
                r"(.+?)\s+"
                r"Начальная цена"
            ),
        ]

        stop_words = [
            "Начальная цена",
            "НМЦК",
            "ИНН",
            "КПП",
            "Объект закупки",
            "Регион",
            "Место поставки",
            "Место нахождения",
            "Почтовый адрес",
            "Адрес электронной почты",
            "Ответственное должностное лицо",
            "Контактный телефон",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            value = match.group(1)

            for stop_word in stop_words:
                position = value.find(stop_word)

                if position >= 0:
                    value = value[:position]

            value = (
                EisZakupkiCollector._clean_text(
                    value
                )
            )

            if value and len(value) >= 3:
                return value[:1000]

        return ""

    # ==================================================================
    # PRICE
    # ==================================================================

    @staticmethod
    def _extract_price(
        block: Any,
    ) -> float | None:

        text = EisZakupkiCollector._clean_text(
            block.get_text(
                " ",
                strip=True,
            )
        )

        return (
            EisZakupkiCollector._parse_money_near_labels(
                text,
                [
                    "Начальная цена",
                    "НМЦК",
                    "максимальная",
                    "цена контракта",
                ],
            )
        )

    @staticmethod
    def _extract_detail_price(
        text: str,
    ) -> float | None:

        value = (
            EisZakupkiCollector._parse_money_near_labels(
                text,
                [
                    "Начальная цена",
                    "Начальная (максимальная) цена",
                    "Максимальное значение цены контракта",
                    "НМЦК",
                ],
            )
        )

        if value is not None:
            return value

        return EisZakupkiCollector._parse_first_money(
            text
        )

    @staticmethod
    def _parse_money_near_labels(
        text: str,
        labels: list[str],
    ) -> float | None:

        for label in labels:
            pattern = (
                re.escape(label)
                + r".{0,200}?"
                + r"([\d\s\u00a0]+"
                r"(?:[,.]\d{1,2})?)"
                + r"\s*"
                + r"(?:₽|руб\.?|рублей|RUB)"
            )

            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            value = (
                EisZakupkiCollector._money_to_float(
                    match.group(1)
                )
            )

            if value is not None and value > 0:
                return value

        return None

    @staticmethod
    def _parse_first_money(
        text: str,
    ) -> float | None:

        pattern = (
            r"([\d\s\u00a0]+"
            r"(?:[,.]\d{1,2})?)"
            r"\s*"
            r"(?:₽|руб\.?|рублей|RUB)"
        )

        for match in re.finditer(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            value = (
                EisZakupkiCollector._money_to_float(
                    match.group(1)
                )
            )

            if value is not None and value > 0:
                return value

        return None

    @staticmethod
    def _money_to_float(
        raw: str,
    ) -> float | None:

        try:
            cleaned = (
                str(raw)
                .replace(" ", "")
                .replace("\u00a0", "")
                .replace(",", ".")
            )

            return float(cleaned)

        except (
            TypeError,
            ValueError,
        ):
            return None

    # ==================================================================
    # REGION
    # ==================================================================

    @staticmethod
    def _extract_region(
        block: Any,
    ) -> str:

        text = EisZakupkiCollector._clean_text(
            block.get_text(
                " ",
                strip=True,
            )
        )

        return (
            EisZakupkiCollector._extract_region_from_text(
                text
            )
        )

    @staticmethod
    def _extract_region_from_text(
        text: str,
    ) -> str:

        text = str(text or "")

        patterns = [
            r"(?:^|\s)Регион\s*[:\-]\s*"
            r"(Вологодская\s+обл\.?|"
            r"[А-ЯЁ][А-ЯЁа-яё\-]+(?:ская|ский|ское)"
            r"(?:\s+обл\.?)?)"
            r"(?:\s|$)",

            r"(?:^|\s)Регион\s+"
            r"(Вологодская\s+обл\.?|"
            r"[А-ЯЁ][А-ЯЁа-яё\-]+(?:ская|ский|ское)"
            r"(?:\s+обл\.?)?)"
            r"(?:\s|$)",

            r"(?:^|\s)Место поставки\s*[:\-]?\s*"
            r"(.{3,300})",

            r"(?:^|\s)Место выполнения работ\s*[:\-]?\s*"
            r"(.{3,300})",

            r"(?:^|\s)Место оказания услуг\s*[:\-]?\s*"
            r"(.{3,300})",
        ]

        stop_markers = [
            "Начальная цена",
            "НМЦК",
            "Заказчик",
            "Окончание подачи заявок",
            "Дата и время",
            "Размещено",
            "Общая информация",
            "Информация о процедуре закупки",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            value = match.group(1)

            for marker in stop_markers:
                if marker in value:
                    value = value.split(marker, 1)[0]

            value = EisZakupkiCollector._clean_text(value)

            if not value:
                continue

            if (
                "Личный кабинет" in value
                or "Официальный сайт единой информационной системы" in value
            ):
                continue

            return value[:500]

        location_patterns = [
            r"Место\s+нахождения\s*[:\-]?\s*"
            r".{0,100}?"
            r"(?:\d{5,6}\s*,?\s*)?"
            r"(?:г\.?\s*)"
            r"([А-ЯЁ][А-ЯЁа-яё\-]+)",

            r"Почтовый\s+адрес\s*[:\-]?\s*"
            r".{0,100}?"
            r"(?:\d{5,6}\s*,?\s*)?"
            r"(?:г\.?\s*)"
            r"([А-ЯЁ][А-ЯЁа-яё\-]+)",
        ]

        for pattern in location_patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            value = EisZakupkiCollector._clean_text(
                match.group(1)
            )

            if value:
                return value[:200]

        return ""

    # ==================================================================
    # DATES
    # ==================================================================

    @staticmethod
    def _parse_date_from_block(
        block: Any,
    ) -> datetime | None:

        text = EisZakupkiCollector._clean_text(
            block.get_text(
                " ",
                strip=True,
            )
        )

        return (
            EisZakupkiCollector._extract_detail_datetime(
                text,
                [
                    "Размещено",
                    "Дата размещения",
                    "Дата публикации",
                    "Опубликовано",
                ],
            )
        )

    @staticmethod
    def _extract_procedure_dates(
        text: str,
    ) -> tuple[
        datetime | None,
        datetime | None,
    ]:

        text = str(text or "")

        # Важно:
        # сначала ищем наиболее точные варианты с датой И временем.
        # Если сначала искать просто "Окончание подачи заявок",
        # ЕИС отдаёт раннюю краткую строку без времени.

        start_labels = [
            "Дата и время начала срока подачи заявок",
            "Дата и время начала подачи заявок",
            "Дата начала срока подачи заявок",
            "Дата начала подачи заявок",
            "Начало подачи заявок",
            "Дата начала приема заявок",
            "Начало приема заявок",
        ]

        end_labels = [
            "Дата и время окончания срока подачи заявок",
            "Дата и время окончания подачи заявок",
            "Дата окончания срока подачи заявок",
            "Дата окончания подачи заявок",
            "Окончание срока подачи заявок",
            "Окончание подачи заявок",
            "Дата окончания приема заявок",
            "Окончание приема заявок",
        ]

        start_date = (
            EisZakupkiCollector._extract_detail_datetime(
                text,
                start_labels,
            )
        )

        end_date = (
            EisZakupkiCollector._extract_detail_datetime(
                text,
                end_labels,
            )
        )

        if start_date is None:
            start_date = (
                EisZakupkiCollector._extract_datetime_by_regex(
                    text,
                    [
                        r"начал\w*\s+"
                        r"(?:подач\w*|при[её]м\w*)"
                        r".{0,150}?"
                        r"(\d{2}\.\d{2}\.\d{4})"
                        r"(?:\s*(?:г\.)?)?"
                        r"(?:\s+(\d{2}:\d{2}))?",
                    ],
                )
            )

        if end_date is None:
            end_date = (
                EisZakupkiCollector._extract_datetime_by_regex(
                    text,
                    [
                        r"окончан\w*\s+"
                        r"(?:срока\s+)?"
                        r"(?:подач\w*|при[её]м\w*)"
                        r".{0,150}?"
                        r"(\d{2}\.\d{2}\.\d{4})"
                        r"(?:\s*(?:г\.)?)?"
                        r"(?:\s+(\d{2}:\d{2}))?",
                    ],
                )
            )

        return start_date, end_date


    @staticmethod
    def _extract_detail_datetime(
        text: str,
        labels: list[str],
    ) -> datetime | None:

        for label in labels:
            pattern = (
                re.escape(label)
                + r"\s*[:\-]?\s*"
                + r"(\d{2}\.\d{2}\.\d{4})"
                + r"(?:\s*(?:г\.)?)?"
                + r"(?:\s+(\d{2}:\d{2}))?"
            )

            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            date_value = match.group(1)

            time_value = (
                match.group(2)
                or "00:00"
            )

            try:
                dt = datetime.strptime(
                    f"{date_value} {time_value}",
                    "%d.%m.%Y %H:%M",
                )

                return dt.replace(
                    tzinfo=timezone.utc
                )

            except ValueError:
                continue

        return None

    @staticmethod
    def _extract_datetime_by_regex(
        text: str,
        patterns: list[str],
    ) -> datetime | None:

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            date_value = match.group(1)

            time_value = (
                match.group(2)
                or "00:00"
            )

            try:
                dt = datetime.strptime(
                    f"{date_value} {time_value}",
                    "%d.%m.%Y %H:%M",
                )

                return dt.replace(
                    tzinfo=timezone.utc
                )

            except ValueError:
                continue

        return None

    # ==================================================================
    # PROCUREMENT METHOD
    # ==================================================================

    @staticmethod
    def _extract_procurement_method(
        text: str,
    ) -> str:

        methods = [
            "Запрос котировок в электронной форме",
            "Электронный аукцион",
            "Открытый конкурс",
            "Конкурс в электронной форме",
            "Запрос предложений",
            "Иной способ определения поставщика",
            "Иной способ",
        ]

        text_lower = str(text or "").lower()

        for method in methods:
            if method.lower() in text_lower:
                return method

        return ""

    # ==================================================================
    # STATUS
    # ==================================================================

    @staticmethod
    def _extract_status(
        text: str,
    ) -> str:

        statuses = [
            "Определение поставщика завершено",
            "Определение поставщика отменено",
            "Закупка отменена",
            "Процедура отменена",
            "Контракт заключен",
            "Контракт исполнен",
            "Контракт расторгнут",
            "Работа комиссии",
            "Подача заявок",
            "Определение поставщика",
        ]

        text_lower = str(text or "").lower()

        for status in statuses:
            if status.lower() in text_lower:
                return status

        return ""

    @staticmethod
    def _is_finished_procedure(
        text: str,
    ) -> bool:

        text_lower = str(text or "").lower()

        finished_markers = [
            "определение поставщика завершено",
            "закупка отменена",
            "процедура отменена",
            "определение поставщика отменено",
            "контракт заключен",
            "контракт исполнен",
            "контракт расторгнут",
        ]

        return any(
            marker in text_lower
            for marker in finished_markers
        )

    # ==================================================================
    # LABELED VALUES
    # ==================================================================

    @staticmethod
    def _extract_labeled_value(
        text: str,
        labels: list[str],
    ) -> str:

        stop_labels = [
            "Организация, осуществляющая размещение",
            "Заказчик",
            "Начальная цена",
            "НМЦК",
            "Размещено",
            "Опубликовано",
            "Окончание подачи заявок",
            "Этап закупки",
            "Регион",
            "Способ определения поставщика",
            "Наименование электронной площадки",
        ]

        stop_pattern = "|".join(
            re.escape(item)
            for item in stop_labels
        )

        for label in labels:
            pattern = (
                re.escape(label)
                + r"\s*[:\-]?\s*"
                + r"(.{2,3000}?)"
                + rf"(?=\s+(?:{stop_pattern})\b|$)"
            )

            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                value = (
                    EisZakupkiCollector._clean_text(
                        match.group(1)
                    )
                )

                if value:
                    return value[:3000]

        return ""

    @staticmethod
    def _extract_between(
        text: str,
        start_label: str,
        end_label: str,
    ) -> str:

        pattern = (
            re.escape(start_label)
            + r"\s+(.+?)\s+"
            + re.escape(end_label)
        )

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            return ""

        return (
            EisZakupkiCollector._clean_text(
                match.group(1)
            )[:3000]
        )

    @staticmethod
    def _extract_description(
        text: str,
    ) -> str:

        marker = "Объект закупки"

        pos = text.find(marker)

        if pos >= 0:
            return text[
                pos:pos + 10000
            ]

        return text[:10000]

    # ==================================================================
    # CAPTCHA
    # ==================================================================

    @staticmethod
    def _has_captcha(
        html: str,
    ) -> bool:

        if not html:
            return False

        lower = html.lower()

        strong_markers = [
            "g-recaptcha",
            "hcaptcha",
            "cf-chl-captcha",
            "captcha-container",
            "captcha__container",
            "recaptcha",
            "checkbot",
        ]

        for marker in strong_markers:
            if marker in lower:
                return True

        title_match = re.search(
            r"<title[^>]*>(.*?)</title>",
            lower,
            flags=re.DOTALL,
        )

        if title_match:
            title = re.sub(
                r"\s+",
                " ",
                title_match.group(1),
            ).strip()

            if any(
                word in title
                for word in (
                    "captcha",
                    "проверка",
                    "робот",
                    "check bot",
                )
            ):
                return True

        return False

    # ==================================================================
    # HTTP
    # ==================================================================

    def _get(
        self,
        url: str,
        params: dict | None = None,
    ) -> requests.Response:
        """Выполнить GET-запрос к ЕИС с повтором временных ошибок."""

        max_attempts = 3

        retry_statuses = {
            429,
            500,
            502,
            503,
            504,
        }

        for attempt in range(
            1,
            max_attempts + 1,
        ):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                )

                if response.status_code in retry_statuses:
                    if attempt < max_attempts:
                        delay = 2 * attempt

                        logger.warning(
                            "ЕИС: HTTP %s | попытка %d/%d | "
                            "повтор через %d сек.",
                            response.status_code,
                            attempt,
                            max_attempts,
                            delay,
                        )

                        time.sleep(delay)
                        continue

                response.raise_for_status()

                return response

            except requests.RequestException as exc:
                status_code = getattr(
                    exc.response,
                    "status_code",
                    None,
                )

                if (
                    status_code in retry_statuses
                    and attempt < max_attempts
                ):
                    delay = 2 * attempt

                    logger.warning(
                        "ЕИС: временная HTTP ошибка %s | "
                        "попытка %d/%d | повтор через %d сек.: %s",
                        status_code,
                        attempt,
                        max_attempts,
                        delay,
                        exc,
                    )

                    time.sleep(delay)
                    continue

                raise

        raise RuntimeError(
            f"ЕИС: не удалось получить страницу после "
            f"{max_attempts} попыток: {url}"
        )
    # ==================================================================
    # UTILS
    # ==================================================================

    @staticmethod
    def _normalize_datetime(
        value: datetime,
    ) -> datetime:

        if value.tzinfo is None:
            return value.replace(
                tzinfo=timezone.utc
            )

        return value.astimezone(
            timezone.utc
        )

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
