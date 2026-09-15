"""Conservative public fallback for Russian procurement portals.

This adapter is used only when the first-party portal is unreachable from the
runner. It reads TenderGuru's public thematic indexes, never authenticates or
bypasses access controls, and keeps the original aggregator URL as provenance.
The resulting Tender still carries the requested logical platform so the rest
of the pipeline can process it uniformly.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.models.tender import Tender

BASE = "https://www.tenderguru.ru"
TOPIC_URLS = {
    "станок": "/tematiki_tenderov/tendery-na-stanki",
    "подшипник": "/tematiki_tenderov/tender-podshipniki",
    "лебедка": "/tematiki_tenderov/tendery-na-liftovoe-oborudovanie",
}
VARIANTS = {
    "станок": ("станок", "станка", "станки", "станков", "станкам", "станками", "станке", "станком"),
    "подшипник": ("подшипник", "подшипника", "подшипники", "подшипников", "подшипнику", "подшипникам", "подшипником", "подшипниками", "подшипнике", "подшипниках"),
    "лебедка": ("лебедка", "лебедки", "лебедку", "лебедкой", "лебедок", "лебедкам", "лебедками"),
}
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "TenderIntelligenceAgent/1.0 (+public-fallback)",
    "Accept-Language": "ru-RU,ru;q=0.9",
})


def _norm(value: str) -> str:
    return re.sub(r"[^0-9a-zа-я]+", " ", str(value or "").casefold().replace("ё", "е")).strip()


def matches_keyword(text: str, keyword: str) -> bool:
    normalized = _norm(text)
    query = _norm(keyword)
    variants = VARIANTS.get(query, (query,))
    return any(re.search(rf"(?<![а-яa-z0-9]){re.escape(_norm(v))}(?![а-яa-z0-9])", normalized) for v in variants)


def search(
    *,
    platform: str,
    keyword: str,
    timeout: int = 15,
    max_pages: int = 3,
    max_results: int = 100,
) -> list[Tender]:
    topic = TOPIC_URLS.get(_norm(keyword))
    if not topic:
        return []
    results: dict[str, Tender] = {}
    for page_no in range(1, max_pages + 1):
        url = urljoin(BASE, topic)
        if page_no > 1:
            url += f"?page={page_no}"
        response = _SESSION.get(url, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.select("a[href*='/tender/']"):
            href = urljoin(BASE, link.get("href", ""))
            match = re.search(r"/tender/(\d+)", href)
            if not match:
                continue
            external_id = match.group(1)
            node = link
            block = node
            for _ in range(5):
                parent = getattr(block, "parent", None)
                if parent is None:
                    break
                text = " ".join(parent.stripped_strings)
                if len(text) >= 40:
                    block = parent
                    break
                block = parent
            text = " ".join(block.stripped_strings)
            if not matches_keyword(text, keyword):
                continue
            if platform == "rts_tender" and not re.search(r"ртс[-\\s]?тендер", _norm(text), re.I):
                continue
            if platform == "eis" and not re.search(r"44\s*-?\s*фз|223\s*-?\s*фз", text, re.I):
                continue
            title = " ".join(link.stripped_strings).strip() or text[:1000]
            results[external_id] = Tender(
                platform=platform,
                external_id=external_id,
                title=title[:1000],
                url=href,
                description=text[:10000],
                raw_data={
                    "source": "tenderguru_public_fallback",
                    "source_url": url,
                    "source_platform": platform,
                    "keyword": keyword,
                },
            )
            if len(results) >= max_results:
                return list(results.values())
    return list(results.values())
