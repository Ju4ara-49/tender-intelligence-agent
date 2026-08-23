"""Deep diagnostic probe for B2B-Center modern search.

The modern B2B-Center search is server-rendered. This probe captures the
actual search page, result-link DOM snippets, network requests/responses and
an intentionally compact diagnostic file so the production collector can be
rebuilt from observed markup instead of the obsolete /market/ table parser.

Run locally from the project root:
    python tools/b2b_center_network_probe.py станок

Outputs are written to output/b2b_network_probe_<timestamp>.txt and
output/b2b_search_dom_<timestamp>.html.
"""

from __future__ import annotations

import json
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

INTERESTING_TOKENS = (
    "/api/", "graphql", "search", "market-search", "purchase",
    "procurement", "procedure", "tender", "trade", "feed", ".json",
)


def compact(text: str, limit: int = 12000) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit] + " ...[TRUNCATED]"


def safe_headers(headers: dict[str, str]) -> dict[str, str]:
    blocked = {"cookie", "authorization", "proxy-authorization", "set-cookie"}
    return {k: v for k, v in headers.items() if k.lower() not in blocked}


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
    dom_output = OUTPUT_DIR / f"b2b_search_dom_{stamp}.html"

    requests_log: list[str] = []
    responses_log: list[str] = []
    websocket_log: list[str] = []
    console_log: list[str] = []
    result_links: list[str] = []
    result_dom: list[str] = []
    script_urls: list[str] = []
    relevant_scripts: list[str] = []
    response_bodies: dict[str, str] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="ru-RU")
        page = context.new_page()

        def is_interesting(url_value: str) -> bool:
            low = url_value.lower()
            return any(token in low for token in INTERESTING_TOKENS)

        def on_request(request):
            req_type = request.resource_type
            if is_interesting(request.url) or req_type in {"xhr", "fetch", "websocket"}:
                requests_log.append(
                    f"{req_type.upper()} {request.method} {request.url}\n"
                    f"  POST={request.post_data or ''}\n"
                    f"  HEADERS={json.dumps(safe_headers(request.all_headers()), ensure_ascii=False)}"
                )

        def on_response(response):
            req_type = response.request.resource_type
            if not (is_interesting(response.url) or req_type in {"xhr", "fetch"}):
                return
            content_type = response.headers.get("content-type", "")
            line = f"{response.status} {content_type} {response.url}"
            try:
                body = response.text()
                if "json" in content_type.lower() or req_type in {"xhr", "fetch"}:
                    line += f"\n  BODY={compact(body)}"
                    if len(response_bodies) < 100:
                        response_bodies[response.url] = body[:100000]
            except Exception as exc:
                line += f"\n  BODY_READ_ERROR={exc}"
            responses_log.append(line)

        def on_websocket(ws):
            websocket_log.append(f"OPEN {ws.url}")
            ws.on("framereceived", lambda payload: websocket_log.append(
                f"RECV {ws.url}: {compact(str(payload), 5000)}"
            ))
            ws.on("framesent", lambda payload: websocket_log.append(
                f"SEND {ws.url}: {compact(str(payload), 5000)}"
            ))

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("websocket", on_websocket)
        page.on("console", lambda msg: console_log.append(
            f"{msg.type}: {compact(msg.text, 3000)}"
        ))

        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        # Save the real server-rendered DOM. This is the key artifact for
        # rebuilding the requests/BeautifulSoup collector.
        dom_output.write_text(page.content(), encoding="utf-8")

        for i in range(page.locator("script").count()):
            script = page.locator("script").nth(i)
            src = script.get_attribute("src") or ""
            if src:
                script_urls.append(src)
            else:
                text = script.inner_text()
                if any(token in text.lower() for token in INTERESTING_TOKENS):
                    relevant_scripts.append(compact(text, 20000))

        # Capture result anchors and their nearest useful DOM container.
        links = page.locator("a[href]")
        seen = set()
        for i in range(min(links.count(), 3000)):
            link = links.nth(i)
            href = link.get_attribute("href") or ""
            text = compact(link.inner_text(), 1000)
            if not href or href in seen:
                continue
            seen.add(href)
            low = href.lower()
            if "/tender-" in low or "/tender/" in low or "/procedure" in low or re.search(r"tender-\d{5,}", low):
                result_links.append(f"{text} | {href}")
                try:
                    result_dom.append(compact(link.evaluate(
                        "el => { let n=el; for(let i=0;i<5 && n;i++,n=n.parentElement){ if((n.innerText||'').length>80) return n.outerHTML; } return el.outerHTML; }"
                    ), 12000))
                except Exception:
                    pass

        body_text = compact(page.locator("body").inner_text(), 30000)
        controls: list[str] = []
        for selector in ("button", "[role='button']", "input", "select", "[aria-label]"):
            locator = page.locator(selector)
            for i in range(min(locator.count(), 500)):
                node = locator.nth(i)
                try:
                    controls.append(
                        f"{selector}: text={compact(node.inner_text(), 500)!r} "
                        f"aria={node.get_attribute('aria-label')!r} "
                        f"name={node.get_attribute('name')!r} "
                        f"value={node.get_attribute('value')!r} "
                        f"href={node.get_attribute('href')!r}"
                    )
                except Exception:
                    pass

        local_storage = page.evaluate("() => Object.fromEntries(Object.entries(localStorage))")
        session_storage = page.evaluate("() => Object.fromEntries(Object.entries(sessionStorage))")

        # Compact diagnostic section: easy to inspect without opening the
        # entire 300-500 KB DOM dump.
        compact_output = OUTPUT_DIR / f"b2b_search_compact_{stamp}.txt"
        with compact_output.open("w", encoding="utf-8") as fh:
            fh.write(f"URL: {url}\nKEYWORD: {keyword}\nTIME: {datetime.now().isoformat()}\n\n")
            fh.write("=== NETWORK REQUESTS ===\n" + "\n\n".join(requests_log) + "\n\n")
            fh.write("=== NETWORK RESPONSES ===\n" + "\n\n".join(responses_log) + "\n\n")
            fh.write("=== RESULT LINKS ===\n" + "\n".join(result_links[:100]) + "\n\n")
            fh.write("=== RESULT DOM SNIPPETS ===\n" + "\n\n".join(result_dom[:50]) + "\n\n")
            fh.write("=== BODY SUMMARY ===\n" + body_text + "\n")

        with output.open("w", encoding="utf-8") as fh:
            fh.write(f"URL: {url}\nKEYWORD: {keyword}\nTIME: {datetime.now().isoformat()}\n\n")
            fh.write("=== BODY SUMMARY ===\n" + body_text + "\n\n")
            fh.write("=== CONTROLS ===\n" + "\n".join(controls) + "\n\n")
            fh.write("=== SCRIPT URLS ===\n" + "\n".join(script_urls) + "\n\n")
            fh.write("=== RELEVANT INLINE SCRIPTS ===\n" + "\n\n".join(relevant_scripts) + "\n\n")
            fh.write("=== RESULT-LIKE LINKS ===\n" + "\n".join(result_links) + "\n\n")
            fh.write("=== NETWORK REQUESTS ===\n" + "\n\n".join(requests_log) + "\n\n")
            fh.write("=== NETWORK RESPONSES ===\n" + "\n\n".join(responses_log) + "\n\n")
            fh.write("=== WEBSOCKETS ===\n" + "\n".join(websocket_log) + "\n\n")
            fh.write("=== CONSOLE ===\n" + "\n".join(console_log) + "\n\n")
            fh.write("=== LOCAL STORAGE ===\n" + json.dumps(local_storage, ensure_ascii=False, indent=2) + "\n\n")
            fh.write("=== SESSION STORAGE ===\n" + json.dumps(session_storage, ensure_ascii=False, indent=2) + "\n\n")
            fh.write("=== SAVED RESPONSE BODIES ===\n")
            for response_url, body in response_bodies.items():
                fh.write(f"\n--- {response_url} ---\n{body[:100000]}\n")

        browser.close()

    print(f"B2B-Center deep network probe completed: {output}")
    print(f"DOM saved: {dom_output}")
    print(f"Compact saved: {compact_output}")
    print(f"Result-like links: {len(result_links)}")
    print(f"Result DOM snippets: {len(result_dom)}")
    print(f"Scripts: {len(script_urls)}")
    print(f"Network requests: {len(requests_log)}")
    print(f"Network responses: {len(responses_log)}")
    print(f"WebSockets: {len(websocket_log)}")
    print(f"Saved response bodies: {len(response_bodies)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
