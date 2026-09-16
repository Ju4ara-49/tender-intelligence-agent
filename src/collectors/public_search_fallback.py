"""Public search-engine fallback for procurement portal discovery.

This is a last-resort discovery adapter. It only consumes ordinary public
search-result pages and never attempts to bypass authentication, CAPTCHA,
WAFs, robots rules, or other portal access controls.
"""
from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

from src.models.tender import Tender

logger = logging.getLogger(__name__)

PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "eis": ("zakupki.gov.ru",),
    "b2b_center": ("b2b-center.ru",),
    "fabrikant": ("fabrikant.ru",),
    "rts_tender": ("rts-tender.ru",),
    "tmk": ("tmk-group.com",),
    "rosatom": ("rosatom.ru",),
}

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (compatible; TenderIntelligenceAgent/1.0; public-discovery)",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
    }
)


def _norm(value: str) -> str:
    return re.sub(r"[^0-9a-zа-я]+", " ", str(value or "").casefold().replace("ё", "е")).strip()


def _allowed(url: str, platform: str) -> bool:
    host = urlparse(url).hostname or ""
    host = host.casefold().removeprefix("www.")
    return any(host == domain or host.endswith("." + domain) for domain in PLATFORM_DOMAINS.get(platform, ()))


def _query(platform: str, keyword: str) -> str:
    domains = PLATFORM_DOMAINS.get(platform, ())
    site = " OR ".join(f"site:{domain}" for domain in domains)
    return f"{site} {keyword}".strip()


def _keyword_match(text: str, keyword: str) -> bool:
    normalized = _norm(text)
    query = _norm(keyword)
    if not query:
        return False
    if query in normalized:
        return True
    tokens = normalized.split()
    for token in tokens:
        if len(query) >= 6 and len(token) >= 6 and query[:-2] in token:
            return True
    return False


def _bing_results(html: str, platform: str, keyword: str) -> list[tuple[str, str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str, str]] = []
    for item in soup.select("li.b_algo"):
        anchor = item.select_one("h2 a[href]")
        if anchor is None:
            continue
        url = str(anchor.get("href", "")).strip()
        title = " ".join(anchor.stripped_strings).strip()
        caption = item.select_one(".b_caption") or item
        description = " ".join(caption.stripped_strings).strip()
        if _allowed(url, platform) and _keyword_match(f"{title} {description}", keyword):
            results.append((url, title, description))
    return results


def _google_results(html: str, platform: str, keyword: str) -> list[tuple[str, str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        url = str(anchor.get("href", "")).strip()
        if not url.startswith("http") or url in seen or not _allowed(url, platform):
            continue
        title = " ".join(anchor.stripped_strings).strip()
        parent = anchor.parent
        description = " ".join(parent.parent.stripped_strings).strip() if parent and parent.parent else title
        if not title or not _keyword_match(f"{title} {description}", keyword):
            continue
        seen.add(url)
        results.append((url, title, description))
    return results


def _yandex_results(html: str, platform: str, keyword: str) -> list[tuple[str, str, str]]:
    """Parse Yandex's public HTML result page without relying on JS."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    selectors = (
        "li.serp-item",
        "div.organic",
        "div[data-cid]",
    )
    nodes = []
    for selector in selectors:
        nodes.extend(soup.select(selector))
    if not nodes:
        nodes = soup.select("a[href]")

    for node in nodes:
        anchors = node.select("a[href]") if hasattr(node, "select") else []
        for anchor in anchors or ([node] if getattr(node, "name", None) == "a" else []):
            url = str(anchor.get("href", "")).strip()
            if not url.startswith("http") or url in seen or not _allowed(url, platform):
                continue
            title_node = anchor.select_one("h2") or anchor
            title = " ".join(title_node.stripped_strings).strip()
            description = " ".join(node.stripped_strings).strip()
            if not title or not _keyword_match(f"{title} {description}", keyword):
                continue
            seen.add(url)
            results.append((url, title, description))
            break
    return results


def _stable_id(url: str) -> str:
    return "public-search-" + hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]


def _request(url: str, timeout: int) -> str:
    response = _SESSION.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def search(*, platform: str, keyword: str, timeout: int = 15, max_results: int = 25) -> list[Tender]:
    """Discover public portal pages through Bing, Yandex, then Google."""
    if platform not in PLATFORM_DOMAINS or not str(keyword).strip():
        return []

    q = _query(platform, str(keyword).strip())
    engines = (
        ("bing", f"https://www.bing.com/search?q={quote_plus(q)}", _bing_results),
        ("yandex", f"https://yandex.ru/search/?text={quote_plus(q)}", _yandex_results),
        ("google", f"https://www.google.com/search?q={quote_plus(q)}", _google_results),
    )
    found: dict[str, Tender] = {}
    errors: list[str] = []

    for engine, url, parser in engines:
        try:
            html = _request(url, timeout)
            rows = parser(html, platform, keyword)
        except Exception as exc:
            errors.append(f"{engine}: {exc}")
            continue
        for result_url, title, description in rows:
            external_id = _stable_id(result_url)
            found[external_id] = Tender(
                platform=platform,
                external_id=external_id,
                title=title[:1000],
                url=result_url,
                description=description[:10000],
                detail_status="not_loaded",
                raw_data={
                    "source": "public_search_engine_fallback",
                    "source_engine": engine,
                    "source_url": url,
                    "keyword": keyword,
                    "details_loaded": False,
                },
            )
            if len(found) >= max_results:
                return list(found.values())[:max_results]
        if found:
            return list(found.values())[:max_results]

    if errors:
        logger.warning("public search fallback failed for %s/%r: %s", platform, keyword, "; ".join(errors))
    return []
