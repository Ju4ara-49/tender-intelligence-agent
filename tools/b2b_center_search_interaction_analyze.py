"""Analyze a saved B2B-Center search interaction probe.

Run from project root:
    python tools\\b2b_center_search_interaction_analyze.py debug_artifacts\\b2b_search_interaction_YYYYMMDD_HHMMSS.json

The analyzer is intentionally offline: it reads the probe JSON and extracts
search-related requests/responses, forms, tender links, and likely API/HTML
sources. It does not contact B2B-Center.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEBUG_DIR = PROJECT_ROOT / "debug_artifacts"

TOKEN_RE = re.compile(r"(?:/api/|api/|graphql|search|market-search|market/|tender-|purchase|feed|xhr|fetch)", re.I)
JSON_CT_RE = re.compile(r"json|javascript|graphql", re.I)


def compact(value: object, limit: int = 5000) -> str:
    text = re.sub(r"\\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit] + " ...[TRUNCATED]"


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Probe JSON root must be an object")
    return data


def request_score(item: dict) -> int:
    url = str(item.get("url", "")).lower()
    method = str(item.get("method", "")).upper()
    post = str(item.get("post_data") or "").lower()
    score = 0
    for token, weight in (("/api/", 8), ("graphql", 8), ("search", 6), ("market-search", 8), ("purchase", 5), ("feed", 4), ("tender", 4), ("market/", 3)):
        if token in url:
            score += weight
    if method == "POST":
        score += 3
    if post:
        score += 2
    if item.get("type") in {"xhr", "fetch"}:
        score += 3
    return score


def response_score(item: dict) -> int:
    url = str(item.get("url", "")).lower()
    body = str(item.get("body") or "").lower()
    score = 0
    for token, weight in (("/api/", 8), ("graphql", 8), ("search", 6), ("market-search", 8), ("purchase", 5), ("feed", 4), ("tender", 4), ("market/", 3)):
        if token in url:
            score += weight
    if item.get("type") in {"xhr", "fetch"}:
        score += 4
    if body and ("tender" in body or "search" in body or "purchase" in body):
        score += 4
    if JSON_CT_RE.search(str(item.get("content_type", ""))):
        score += 2
    return score


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python tools\\b2b_center_search_interaction_analyze.py <probe.json>")
        return 2

    source = Path(sys.argv[1])
    if not source.is_absolute():
        source = PROJECT_ROOT / source
    if not source.exists():
        print(f"ERROR: probe file not found: {source}")
        return 2

    data = load(source)
    keyword = str(data.get("keyword") or "")
    requests = data.get("requests") or []
    responses = data.get("responses") or []
    results = data.get("results") or []
    forms = data.get("forms_before_submit") or []

    ranked_requests = sorted(requests, key=request_score, reverse=True)
    ranked_responses = sorted(responses, key=response_score, reverse=True)

    # Deduplicate by URL while retaining the highest-value request/response.
    def dedupe(items: list[dict]) -> list[dict]:
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            key = (str(item.get("method", "")), str(item.get("url", "")))
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    ranked_requests = dedupe(ranked_requests)
    ranked_responses = dedupe(ranked_responses)

    lines: list[str] = []
    lines.append("B2B-CENTER SEARCH INTERACTION ANALYSIS")
    lines.append(f"Source: {source}")
    lines.append(f"Keyword: {keyword}")
    lines.append(f"Started URL: {data.get('started_url', '')}")
    lines.append(f"Final URL: {data.get('final_url', '')}")
    lines.append(f"Result links: {len(results)}")
    lines.append(f"Requests captured: {len(requests)}")
    lines.append(f"Responses captured: {len(responses)}")
    lines.append("")

    lines.append("=== FORMS BEFORE SUBMIT ===")
    for form in forms:
        html = str(form.get("outer_html", ""))
        if "f_keyword" in html or "search" in html.lower():
            lines.append(f"FORM #{form.get('index')}: action={form.get('action')!r} method={form.get('method')!r}")
            lines.append(compact(html, 8000))
    lines.append("")

    lines.append("=== TOP SEARCH/NETWORK REQUESTS ===")
    for item in ranked_requests[:40]:
        if request_score(item) <= 0:
            continue
        lines.append(
            f"[{request_score(item):02d}] {item.get('method','')} {item.get('type','')} {item.get('url','')}"
        )
        if item.get("post_data"):
            lines.append(f"  POST_DATA: {compact(item.get('post_data'), 4000)}")
    lines.append("")

    lines.append("=== TOP SEARCH/NETWORK RESPONSES ===")
    for item in ranked_responses[:40]:
        if response_score(item) <= 0:
            continue
        lines.append(
            f"[{response_score(item):02d}] HTTP {item.get('status')} {item.get('type','')} {item.get('content_type','')} {item.get('url','')}"
        )
        if item.get("body"):
            lines.append(f"  BODY: {compact(item.get('body'), 8000)}")
    lines.append("")

    lines.append("=== RESULT LINKS ===")
    for i, item in enumerate(results[:50], 1):
        lines.append(f"{i:02d}. {item.get('href','')}")
        lines.append(f"    TEXT: {compact(item.get('text',''), 1500)}")
        lines.append(f"    CLASS: {item.get('class','')}")
        parent = item.get("parent_html") or ""
        if parent:
            lines.append(f"    PARENT_HTML: {compact(parent, 5000)}")
    lines.append("")

    # Heuristic summary, deliberately marked as heuristic rather than fact.
    urls = [str(x.get("url", "")) for x in requests + responses]
    api_like = [u for u in urls if "/api/" in u.lower() or "graphql" in u.lower()]
    xhr_fetch = [x for x in requests if x.get("type") in {"xhr", "fetch"}]
    lines.append("=== HEURISTIC CONCLUSION ===")
    if api_like:
        lines.append(f"API/GraphQL-like URLs found: {len(set(api_like))}")
        for u in list(dict.fromkeys(api_like))[:20]:
            lines.append(f"  {u}")
    else:
        lines.append("No explicit /api/ or GraphQL URL was captured in the filtered network log.")
    lines.append(f"XHR/fetch requests: {len(xhr_fetch)}")
    lines.append("The actual search source should be selected from the response bodies above, not inferred from the final /market/ URL alone.")

    stamp = source.stem.replace("b2b_search_interaction_", "")
    out = DEBUG_DIR / f"b2b_search_interaction_analysis_{stamp}.txt"
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")

    print(f"B2B-Center interaction analysis completed: {out}")
    print(f"Keyword: {keyword}")
    print(f"Final URL: {data.get('final_url', '')}")
    print(f"Results: {len(results)}")
    print(f"Top API/search requests: {sum(1 for x in ranked_requests[:40] if request_score(x) > 0)}")
    print(f"Top API/search responses: {sum(1 for x in ranked_responses[:40] if response_score(x) > 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
