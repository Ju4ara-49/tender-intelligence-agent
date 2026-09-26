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
from typing import Callable
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


def _resolve_canonical(query: str) -> str | None:
    """Resolve a keyword in any declined word form to its canonical
    (nominative singular) key used by TOPIC_URLS/VARIANTS. Without this,
    a plural or otherwise declined query (e.g. "станки", "подшипники")
    would not be found by the dict's exact-key lookup, even though it is
    a fully valid form of a supported keyword group."""
    if query in VARIANTS:
        return query
    for canonical, forms in VARIANTS.items():
        if query in forms:
            return canonical
    return None


def matches_keyword(text: str, keyword: str) -> bool:
    normalized = _norm(text)
    query = _norm(keyword)
    canonical = _resolve_canonical(query)
    variants = VARIANTS.get(canonical, (query,)) if canonical else (query,)
    return any(re.search(rf"(?<![а-яa-z0-9]){re.escape(_norm(v))}(?![а-яa-z0-9])", normalized) for v in variants)


def search(
    *,
    platform: str,
    keyword: str,
    timeout: int = 15,
    max_pages: int = 3,
    max_results: int = 100,
    http_get: Callable | None = None,
) -> list[Tender]:
    canonical = _resolve_canonical(_norm(keyword))
    topic = TOPIC_URLS.get(canonical) if canonical else None
    if not topic:
        return []
    getter = http_get or _SESSION.get

    def _fetch(url: str) -> requests.Response:
        try:
            return getter(url, timeout=timeout)
        except TypeError:
            return getter(url)

    results: dict[str, Tender] = {}
    for page_no in range(1, max_pages + 1):
        url = urljoin(BASE, topic)
        if page_no > 1:
            url += f"?page={page_no}"
        response = _fetch(url)
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
            if platform == "rts_tender" and not re.search(r"ртс[-\s]?тендер", _norm(text), re.I):
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
