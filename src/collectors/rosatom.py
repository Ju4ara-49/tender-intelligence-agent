"""Collector for the public Rosatom procurement portal.

The Rosatom portal is a legacy/JS-heavy public site. The collector uses
Playwright and the portal's published procurements page. It does not bypass
WAF, CAPTCHA, authentication, or other access controls.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

from src.collectors.browser_public import _BrowserTenderCollector
from src.models.tender import Tender

logger = logging.getLogger(__name__)


class RosatomCollector(_BrowserTenderCollector):
    """Public procurement search on zakupki.rosatom.ru."""

    platform = "rosatom"
    BASE_URL = "https://zakupki.rosatom.ru/?link=published_procurements"
    SEARCH_HINTS = ("Поиск", "Найти", "Искать", "Найти закупку", "Поиск закупок")
    LINK_HINTS = ("procurements", "obj_id", "published_procurements")
    ALLOW_PUBLISHED_LISTING_FALLBACK = True

    @classmethod
    def _tender_matches_query(cls, tender: Tender, query: str) -> bool:
        """Match a Rosatom numeric procedure id as well as normal keywords.

        ``get_details()`` reuses the public search surface with the numeric
        Rosatom ``obj_id``. The published table keeps that id in the row's
        first column, while the procedure title does not contain it. The
        generic browser relevance gate therefore rejected the exact procedure
        after a successful search. Treat an exact numeric external id as a
        verified match; normal keyword matching remains unchanged.
        """
        normalized = cls._normalize_search_text(query)
        external_id = cls._normalize_search_text(str(tender.external_id or ""))
        if normalized and external_id and normalized == external_id and normalized.isdigit():
            return True
        return super()._tender_matches_query(tender, query)

    @staticmethod
    def _clean_cell(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n;")

    @staticmethod
    def _split_procurement_number(value: str) -> tuple[str, str]:
        text = RosatomCollector._clean_cell(value)
        match = re.search(r"(\d+)\s*\(\s*(\d+)\s*\)", text)
        if match:
            return match.group(1), match.group(2)
        match = re.search(r"\b(\d{4,})\b", text)
        return (match.group(1), "") if match else ("", "")

    def _row_to_tender(self, cells: list[str], href: str = "") -> Tender | None:
        if not cells:
            return None
        number, official_number = self._split_procurement_number(cells[0])
        if not number:
            return None
        title = self._clean_cell(cells[1]) if len(cells) > 1 else ""
        if not title or title.lower() in {"предмет договора", "наименование закупки"}:
            return None

        price = self._extract_price("НМЦ, руб: " + (cells[2] if len(cells) > 2 else ""))
        customer = self._clean_cell(cells[3]) if len(cells) > 3 else ""
        published_at = self._extract_datetime(
            "Дата публикации " + (cells[4] if len(cells) > 4 else ""),
            ("Дата публикации",),
        )
        deadline_text = self._clean_cell(cells[5]) if len(cells) > 5 else ""
        deadline_text = re.sub(r"\bЭтап\s*\d+\s*:\s*", "", deadline_text, flags=re.I)
        deadline = self._extract_datetime("Дата окончания " + deadline_text, ("Дата окончания",))
        platform = self._clean_cell(cells[6]) if len(cells) > 6 else ""
        region = self._clean_cell(cells[7]) if len(cells) > 7 else ""

        url = href or self.BASE_URL
        raw_data = {
            "source": "zakupki.rosatom.ru",
            "obj_id": number,
            "official_number": official_number,
            "discovery_only": not bool(href),
            "published_at": published_at.isoformat() if published_at else None,
            "end_date": deadline.isoformat() if deadline else None,
            "procurement_platform": platform,
        }
        return Tender(
            platform=self.platform,
            external_id=number,
            title=title[:1000],
            url=url,
            description=title,
            price=price,
            deadline=deadline,
            published_at=published_at,
            end_date=deadline,
            customer=customer,
            region=region,
            raw_data=raw_data,
        )

    def _parse_results(self, html: str) -> list[Tender]:
        """Parse direct procedure links and the current published table."""
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        soup = BeautifulSoup(html, "html.parser")
        results: list[Tender] = []
        seen: set[str] = set()
        base_host = urlparse(self.BASE_URL).netloc.lower()
        body_text = " ".join(soup.stripped_strings).lower()
        if "web application firewall" in body_text or "временно заблокирован" in body_text:
            logger.warning("rosatom: официальный портал вернул страницу WAF; поиск невозможен без обхода защиты")
            return []

        for anchor in soup.find_all("a", href=True):
            raw_href = str(anchor.get("href", "")).strip()
            href = urljoin(self.BASE_URL, raw_href)
            parsed = urlparse(href)
            if parsed.netloc and parsed.netloc.lower() != base_host:
                continue
            query = parse_qs(parsed.query)
            obj_id = (query.get("obj_id") or [""])[0].strip()
            title = self._clean_cell(" ".join(anchor.stripped_strings))
            if not obj_id or not title or len(title) < 5:
                continue
            if "procurements" not in href.lower() or obj_id in seen:
                continue
            seen.add(obj_id)
            self._urls[obj_id] = href
            results.append(Tender(
                platform=self.platform,
                external_id=obj_id,
                title=title[:1000],
                url=href,
                description=title,
                raw_data={"source": "zakupki.rosatom.ru", "obj_id": obj_id},
            ))

        all_rows = soup.find_all("tr")
        header_index = None
        for index, row in enumerate(all_rows):
            cells = [self._clean_cell(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            lowered = " | ".join(cells).lower()
            if cells and "номер закупки" in lowered and "предмет договора" in lowered:
                header_index = index
                break

        if header_index is not None:
            for row in all_rows[header_index + 1:]:
                cells = [self._clean_cell(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
                if len(cells) < 2:
                    continue
                tender = self._row_to_tender(cells)
                if tender is None or tender.external_id in seen:
                    continue
                seen.add(tender.external_id)
                self._urls[tender.external_id] = self.BASE_URL
                results.append(tender)

        if not results:
            for node in soup.find_all(attrs={"data-procurement-id": True}):
                number = self._clean_cell(node.get("data-procurement-id"))
                if not number or number in seen:
                    continue
                title = self._clean_cell(" ".join(node.stripped_strings))
                if len(title) < 5:
                    continue
                tender = Tender(
                    platform=self.platform,
                    external_id=number,
                    title=title[:1000],
                    url=self.BASE_URL,
                    description=title,
                    raw_data={"source": "zakupki.rosatom.ru", "obj_id": number, "discovery_only": True},
                )
                seen.add(number)
                self._urls[number] = self.BASE_URL
                results.append(tender)

        return results

    def _perform_search(self, page, query: str) -> bool:
        """Use Rosatom's published-procurement filter panel instead of a generic textbox."""
        try:
            panel = page.get_by_role("button", name="Параметры поиска", exact=True).first
            if panel.count() and panel.is_visible():
                panel.click(timeout=1500)
                page.wait_for_timeout(500)
        except Exception:
            pass

        candidates = (
            "input[name*='предмет' i]",
            "input[placeholder*='предмет' i]",
            "input[name*='search' i]",
            "input[type='search']",
        )
        for selector in candidates:
            try:
                locator = page.locator(selector).first
                if locator.count() and locator.is_visible():
                    locator.fill(query, timeout=1500)
                    try:
                        button = page.get_by_role("button", name="Поиск", exact=True).first
                        if button.count() and button.is_visible():
                            button.click(timeout=1500)
                        else:
                            locator.press("Enter", timeout=1500)
                    except Exception:
                        locator.press("Enter", timeout=1500)
                    logger.info("rosatom: SEARCH_SUBMITTED selector=%s query=%s", selector, query)
                    return True
            except Exception:
                continue

        try:
            locator = page.get_by_role("textbox").first
            if locator.count() and locator.is_visible():
                locator.fill(query, timeout=1500)
                try:
                    button = page.get_by_role("button", name="Поиск", exact=True).first
                    if button.count() and button.is_visible():
                        button.click(timeout=1500)
                    else:
                        locator.press("Enter", timeout=1500)
                except Exception:
                    locator.press("Enter", timeout=1500)
                logger.info("rosatom: SEARCH_SUBMITTED selector=role=textbox query=%s", query)
                return True
        except Exception:
            pass

        logger.warning("rosatom: search field not found for query %r", query)
        return False

    def get_details(self, external_id: str) -> Tender | None:
        """Refresh one Rosatom row through the published registry."""
        target = str(external_id).strip()
        if not target:
            return None
        try:
            results = self._search_one(target)
        except Exception as exc:
            logger.warning("rosatom: detail lookup failed %s: %s", target, exc)
            return None
        for tender in results:
            if tender.external_id == target:
                tender.raw_data["discovery_only"] = False
                return tender
        return None

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
        published_at = self._extract_datetime(text, ("Дата публикации", "Дата размещения", "Опубликовано", "Размещено"))
        start_date = self._extract_datetime(text, ("Дата начала", "Начало приема", "Начало подачи"))
        end_date = deadline or self._extract_datetime(text, ("Дата окончания", "Окончание приема", "Окончание подачи"))
        customer = self._extract_labeled_value(text, ("Организатор", "Заказчик", "Организация-заказчик"))
        if not customer:
            match = re.search(r"Организатор\s*[:\-]\s*(.+?)(?:\s+Контактное лицо|\s+Дата|$)", text, re.I)
            if match:
                customer = match.group(1).strip()[:1000]
        region = self._extract_labeled_value(text, ("Регион поставки", "Место поставки", "Место выполнения", "Регион"))
        law_type = self._extract_labeled_value(text, ("Закон", "Вид закона", "Федеральный закон", "Тип закупки"))
        advance_percent = self._extract_percent(text, ("Аванс", "Предоплата", "Размер аванса"))
        postpayment_days = self._extract_days(text, ("Отсрочка платежа", "Срок оплаты", "Условия оплаты", "Постоплата"))
        application_security = self._extract_percent(text, ("Обеспечение заявки", "Обеспечение предложения"))
        contract_security = self._extract_percent(text, ("Обеспечение исполнения", "Обеспечение контракта", "Обеспечение договора"))

        official_number = ""
        match = re.search(r"Номер закупки на официальном сайте ГК «Росатом»\s*[:\-]?\s*(\d+)", text, re.I)
        if match:
            official_number = match.group(1)

        raw_data = {
            "source": url,
            "obj_id": external_id,
            "official_number": official_number,
            "published_at": published_at.isoformat() if published_at else None,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        }
        if advance_percent is not None:
            raw_data["advance_payment"] = {"percent": advance_percent}
        if postpayment_days is not None:
            raw_data["postpayment"] = {"days": postpayment_days}
        if application_security is not None:
            raw_data["application_security"] = {"percent": application_security}
        if contract_security is not None:
            raw_data["contract_security"] = {"percent": contract_security}

        return Tender(
            platform=self.platform,
            external_id=external_id,
            title=title[:1000],
            url=url,
            description=text[:10000],
            price=price,
            deadline=end_date,
            published_at=published_at,
            start_date=start_date,
            end_date=end_date,
            customer=customer,
            region=region,
            law_type=law_type,
            advance_required=advance_percent is not None and advance_percent > 0,
            advance_percent=advance_percent,
            postpayment_days=postpayment_days,
            application_security_percent=application_security,
            contract_security_percent=contract_security,
            raw_data=raw_data,
        )
