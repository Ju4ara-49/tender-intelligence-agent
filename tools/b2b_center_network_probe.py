"""Diagnostic probe for B2B-Center modern search.

Does not change production collectors. Opens the exact modern search URL,
records network requests/responses that may contain search data, and reports
pagination controls and result links. Run locally from the project root:

    python tools/b2b_center_network_probe.py станок

The output is written to output/b2b_network_probe_<timestamp>.txt.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright

BASE_URL = "https://www.b2b-center.ru"
SEARCH_URL = f"{BASE_URL}/app/next/market-search"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output"


def main() -> int:
    keyword = " ".join(sys.argv[1:]).strip() or "станок"
    url = (
        f"{SEARCH_URL}?q={quote_plus(keyword)}"
        "&company_type=2&include_firm_tree=false&sort=date_desc"
        "&trade=buy&show=actual"
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"b2b_network_probe_{stamp}.txt"

    requests_log: list[str] = []
    responses_log: list[str] = []
    result_links: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="ru-RU")
        page = context.new_page()

        def on_request(request):
            req_type = request.resource_type
            low = request.url.lower()
            interesting = any(
                token in low
                for token in (
                    "/api/",
                    "graphql",
                    "search",
                    "market-search",
                    "tender",
                    "procedure",
                    "purchase",
                    ".json",
                )
            )
            if interesting or req_type in {"xhr", "fetch"}:
                requests_log.append(
                    f"{req_type.upper()} {request.method} {request.url}\n"
                    f"  POST={request.post_data or ''}"
                )

        def on_response(response):
            low = response.url.lower()
            if response.request.resource_type not in {"xhr", "fetch"} and not any(
                token in low
                for token in ("/api/", "graphql", "search", "market-search", ".json")
            ):
                return
            content_type = response.headers.get("content-type", "")
            line = f"{response.status} {content_type} {response.url}"
            try:
                if "json" in content_type.lower():
                    body = response.text()
                    body = re.sub(r"\s+", " ", body)
                    if len(body) > 5000:
                        body = body[:5000] + " ...[TRUNCATED]"
                    line += f"\n  BODY={body}"
            except Exception as exc:
                line += f"\n  BODY_READ_ERROR={exc}"
            responses_log.append(line)

        page.on("request", on_request)
        page.on("response", on_response)

        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        # Trigger one controlled scroll so lazy-loaded result pages/data appear.
        for _ in range(5):
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(1000)

        links = page.locator("a[href]")
        seen = set()
        for i in range(min(links.count(), 1000)):
            link = links.nth(i)
            href = link.get_attribute("href") or ""
            text = re.sub(r"\s+", " ", link.inner_text()).strip()
            if not href or href in seen:
                continue
            seen.add(href)
            low = href.lower()
            if any(token in low for token in ("tender", "procedure", "purchase", "trade")) or re.search(r"\d{7,}", href):
                result_links.append(f"{text[:300]} | {href}")

        body_text = re.sub(r"\s+", " ", page.locator("body").inner_text())
        buttons = []
        for i in range(min(page.get_by_role("button").count(), 200)):
            button = page.get_by_role("button").nth(i)
            try:
                txt = re.sub(r"\s+", " ", button.inner_text()).strip()
                if txt:
                    buttons.append(txt)
            except Exception:
                pass

        with output.open("w", encoding="utf-8") as fh:
            fh.write(f"URL: {url}\n")
            fh.write(f"KEYWORD: {keyword}\n")
            fh.write(f"TIME: {datetime.now().isoformat()}\n\n")
            fh.write("=== BODY SUMMARY ===\n")
            fh.write(body_text[:20000] + "\n\n")
            fh.write("=== BUTTONS ===\n")
            fh.write("\n".join(buttons) + "\n\n")
            fh.write("=== RESULT-LIKE LINKS ===\n")
            fh.write("\n".join(result_links) + "\n\n")
            fh.write("=== NETWORK REQUESTS ===\n")
            fh.write("\n\n".join(requests_log) + "\n\n")
            fh.write("=== NETWORK RESPONSES ===\n")
            fh.write("\n\n".join(responses_log) + "\n")

        browser.close()

    print(f"B2B-Center network probe completed: {output}")
    print(f"Result-like links: {len(result_links)}")
    print(f"Network requests captured: {len(requests_log)}")
    print(f"Network responses captured: {len(responses_log)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
