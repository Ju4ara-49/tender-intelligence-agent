from __future__ import annotations

import re
from pathlib import Path

PATH = Path("src/collectors/b2b_center.py")

text = PATH.read_text(encoding="utf-8-sig")

text = text.replace(
    'from urllib.parse import urljoin',
    'from urllib.parse import parse_qs, urlencode, urljoin, urlparse',
)
text = text.replace(
    'SEARCH_URL = f"{BASE_URL}/market/"',
    'SEARCH_URL = f"{BASE_URL}/app/next/market-search/"',
)

# Replace URL fallback lookup with the same modern SSR search page.
text = re.sub(
    r'    def _find_tender_url_by_id\(.*?\n    # =============================================================\=\n    # SEARCH HTTP\n',
    '''    def _find_tender_url_by_id(\n        self,\n        external_id: str,\n    ) -> str | None:\n        """Find the real procedure URL using the modern search page."""\n\n        try:\n            response = self._get(\n                SEARCH_URL,\n                params={\n                    "q": external_id,\n                    "company_type": "2",\n                    "include_firm_tree": "false",\n                    "sort": "date_desc",\n                    "trade": "buy",\n                    "show": "actual",\n                },\n            )\n\n            soup = BeautifulSoup(response.text, "lxml")\n\n            for link in soup.select("a.search-results-title[href]"):\n                href = self._clean_text(link.get("href", ""))\n                if f"tender-{external_id}" not in href:\n                    continue\n\n                url = urljoin(BASE_URL, unescape(href))\n                self._tender_urls[external_id] = url\n                return url\n\n        except Exception:\n            logger.exception(\n                "B2B-Center: ошибка поиска URL по ID %s",\n                external_id,\n            )\n\n        return None\n\n    # =============================================================\n    # SEARCH HTTP\n''',
    text,
    flags=re.DOTALL,
)

# Replace search-page loader.
text = re.sub(
    r'    def _load_search_page\(.*?\n    # =============================================================\n    # SEARCH PARSER\n',
    '''    def _load_search_page(\n        self,\n        keyword: str,\n        page: int = 1,\n    ) -> str:\n        """Load a page from the current B2B-Center SSR search."""\n\n        params = {\n            "q": keyword,\n            "company_type": "2",\n            "include_firm_tree": "false",\n            "sort": "date_desc",\n            "trade": "buy",\n            "show": "actual",\n        }\n        if page > 1:\n            params["page"] = str(page)\n\n        response = self._get(SEARCH_URL, params=params)\n        return response.text\n\n    # =============================================================\n    # SEARCH PARSER\n''',
    text,
    flags=re.DOTALL,
)

# Replace parser: the new page renders result rows without the old table.search-results class.
text = re.sub(
    r'    def _parse_search_html\(.*?\n    # =============================================================\n    # EXTRACTORS\n',
    '''    def _parse_search_html(\n        self,\n        html: str,\n        keyword: str,\n        since: datetime | None = None,\n    ) -> list[Tender]:\n        """Parse modern B2B-Center SSR result rows."""\n\n        soup = BeautifulSoup(html, "lxml")\n        links = soup.select("a.search-results-title[href]")\n\n        logger.info(\n            "B2B-Center: modern search result links: %s",\n            len(links),\n        )\n\n        results: list[Tender] = []\n        seen: set[str] = set()\n\n        for link in links:\n            row = link.find_parent("tr")\n            if row is None:\n                continue\n\n            tender = self._parse_search_row(row, keyword)\n            if tender is None or not tender.external_id:\n                continue\n\n            if tender.external_id in seen:\n                continue\n            seen.add(tender.external_id)\n\n            if since is not None and tender.published_at is not None:\n                if self._normalize_datetime(tender.published_at) < self._normalize_datetime(since):\n                    continue\n\n            results.append(tender)\n\n        logger.info(\n            "B2B-Center: принято %s результатов из современной выдачи",\n            len(results),\n        )\n        return results\n\n    def _parse_search_row(\n        self,\n        row: Any,\n        keyword: str,\n    ) -> Tender | None:\n        """Parse one modern B2B-Center result row."""\n\n        link = row.select_one("a.search-results-title[href]")\n        if link is None:\n            return None\n\n        href = self._clean_text(link.get("href", ""))\n        if not href:\n            return None\n\n        url = urljoin(BASE_URL, unescape(href))\n        title_text = ""\n\n        desc = link.select_one(".search-results-title-desc")\n        if desc is not None:\n            # Work on a copy so that removing decorative nodes does not\n            # mutate the page object used by later parsing.\n            desc_copy = BeautifulSoup(str(desc), "lxml")\n            desc_node = desc_copy.select_one(".search-results-title-desc")\n            if desc_node is not None:\n                for node in desc_node.select(".search-results-title-type"):\n                    node.decompose()\n                for node in desc_node.find_all("small"):\n                    node.decompose()\n                for node in desc_node.find_all("div"):\n                    style = (node.get("style") or "").lower().replace(" ", "")\n                    if "color:#888" in style or "color:#aaa" in style:\n                        node.decompose()\n                title_text = self._clean_text(desc_node.get_text(" ", strip=True))\n\n        if not title_text:\n            title_text = self._clean_text(link.get_text(" ", strip=True))\n\n        external_id = self._extract_external_id(href, link.get_text(" ", strip=True))\n        if not external_id:\n            return None\n\n        title = self._clean_procedure_title(title_text, external_id)\n        if not title:\n            title = self._clean_procedure_title(\n                self._clean_text(link.get_text(" ", strip=True)),\n                external_id,\n            )\n\n        cells = row.select("td")\n        customer = ""\n        published_at = None\n        deadline = None\n\n        # The current SSR table is: category/title | organizer | published | actual until.\n        if len(cells) >= 2:\n            customer = self._clean_text(cells[1].get_text(" ", strip=True))\n        if len(cells) >= 3:\n            published_at = self._parse_date_text(\n                self._clean_text(cells[2].get_text(" ", strip=True))\n            )\n        if len(cells) >= 4:\n            deadline = self._parse_date_text(\n                self._clean_text(cells[3].get_text(" ", strip=True))\n            )\n\n        row_text = self._clean_text(row.get_text(" ", strip=True))\n\n        return Tender(\n            platform=self.platform,\n            external_id=str(external_id),\n            title=title[:1000],\n            url=url,\n            description=row_text[:10000],\n            price=self._extract_price(row_text),\n            currency="RUB",\n            published_at=published_at,\n            deadline=deadline,\n            end_date=deadline,\n            customer=customer[:1000],\n            raw_data={\n                "keyword": keyword,\n                "search_text": row_text[:10000],\n                "search_href": href,\n                "details_url": url,\n                "procurement_method": self._extract_procurement_method(row_text),\n                "search_engine": "b2b-center-next-ssr",\n            },\n        )\n\n    # =============================================================\n    # EXTRACTORS\n''',
    text,
    flags=re.DOTALL,
)

# Replace the public search loop so max_pages controls actual SSR pagination.
old = '''                html = self._load_search_page(keyword)\n\n                found = self._parse_search_html(\n                    html,\n                    keyword,\n                    since,\n                )\n\n                for tender in found:\n                    if tender.external_id:\n                        # Сохраняем настоящий URL для последующей\n                        # загрузки деталей по external_id.\n                        external_id = str(\n                            tender.external_id\n                        )\n\n                        self._tender_urls[\n                            external_id\n                        ] = tender.url\n\n                        if tender.title:\n                            self._tender_titles[\n                                external_id\n                            ] = tender.title\n                        results[tender.unique_key] = tender\n'''
new = '''                for page in range(1, self.max_pages + 1):\n                    html = self._load_search_page(keyword, page=page)\n\n                    found = self._parse_search_html(\n                        html,\n                        keyword,\n                        since,\n                    )\n\n                    if not found:\n                        logger.info(\n                            "B2B-Center: страница %s не дала результатов, остановка пагинации",\n                            page,\n                        )\n                        break\n\n                    for tender in found:\n                        if tender.external_id:\n                            external_id = str(tender.external_id)\n                            self._tender_urls[external_id] = tender.url\n                            if tender.title:\n                                self._tender_titles[external_id] = tender.title\n                            results[tender.unique_key] = tender\n\n                    if len(found) < 20:\n                        break\n'''
if old not in text:
    raise SystemExit("Expected search loop was not found; source was not modified")
text = text.replace(old, new, 1)

PATH.write_text(text, encoding="utf-8")
print(f"Updated {PATH}")
