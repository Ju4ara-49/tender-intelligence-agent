"""Probe the real B2B-Center search form interaction.

Unlike the URL-only probe, this script opens the search UI, fills the actual
keyword field, submits the form, and records the final URL, result DOM and
network traffic. This is intended to discover the real search request used by
the current B2B-Center frontend.

Run from project root:
    python tools\\b2b_center_search_interaction_probe.py станок
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

BASE_URL = "https://www.b2b-center.ru"
START_URL = f"{BASE_URL}/market/"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEBUG_DIR = PROJECT_ROOT / "debug_artifacts"


def compact(text: str, limit: int = 12000) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit] + " ...[TRUNCATED]"


def safe_headers(headers: dict[str, str]) -> dict[str, str]:
    blocked = {"cookie", "authorization", "proxy-authorization", "set-cookie"}
    return {k: v for k, v in headers.items() if k.lower() not in blocked}


def main() -> int:
    keyword = " ".join(sys.argv[1:]).strip() or "станок"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out = DEBUG_DIR / f"b2b_search_interaction_{stamp}.json"

    requests_log: list[dict] = []
    responses_log: list[dict] = []
    forms: list[dict] = []
    result_links: list[dict] = []
    console_log: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="ru-RU")
        page = context.new_page()

        def on_request(request):
            if request.resource_type in {"document", "xhr", "fetch"} or any(
                token in request.url.lower()
                for token in ("search", "market", "tender", "/api/")
            ):
                requests_log.append(
                    {
                        "type": request.resource_type,
                        "method": request.method,
                        "url": request.url,
                        "post_data": request.post_data,
                        "headers": safe_headers(request.all_headers()),
                    }
                )

        def on_response(response):
            if response.request.resource_type not in {"document", "xhr", "fetch"} and not any(
                token in response.url.lower()
                for token in ("search", "market", "tender", "/api/")
            ):
                return
            item = {
                "status": response.status,
                "type": response.request.resource_type,
                "url": response.url,
                "content_type": response.headers.get("content-type", ""),
            }
            try:
                body = response.text()
                if response.request.resource_type in {"xhr", "fetch"} or "json" in item["content_type"].lower():
                    item["body"] = compact(body, 12000)
            except Exception as exc:
                item["body_error"] = str(exc)
            responses_log.append(item)

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("console", lambda msg: console_log.append(f"{msg.type}: {compact(msg.text, 3000)}"))

        page.goto(START_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)

        # Capture every form and its controls before submitting.
        for i in range(page.locator("form").count()):
            form = page.locator("form").nth(i)
            item = {
                "index": i,
                "action": form.get_attribute("action"),
                "method": form.get_attribute("method"),
                "outer_html": compact(form.evaluate("el => el.outerHTML"), 20000),
            }
            forms.append(item)

        # B2B-Center renders more than one f_keyword input. The header search
        # input is present in the DOM but hidden, while the market-search form
        # contains the actual visible field. Always prefer a visible control.
        keyword_candidates = page.locator("input[name='f_keyword']:visible")
        if keyword_candidates.count() == 0:
            # Fallback for future markup changes: inspect all matching inputs
            # and choose the first one that is displayed and editable.
            all_candidates = page.locator("input[name='f_keyword']")
            visible_indices = []
            for i in range(all_candidates.count()):
                candidate = all_candidates.nth(i)
                try:
                    if candidate.is_visible() and candidate.is_editable():
                        visible_indices.append(i)
                except Exception:
                    continue
            if not visible_indices:
                raise RuntimeError("B2B-Center has no visible/editable input[name=f_keyword]")
            keyword_input = all_candidates.nth(visible_indices[0])
        else:
            keyword_input = keyword_candidates.first

        keyword_input.scroll_into_view_if_needed()
        keyword_input.fill(keyword)

        form = keyword_input.locator("xpath=ancestor::form[1]")
        if form.count() == 0:
            raise RuntimeError("Search input has no parent form")

        # Prefer the real submit control inside the form. If the site handles
        # submission with JS, pressing Enter triggers the same UI path.
        submit_candidates = form.locator(
            "input[type='submit']:visible, button[type='submit']:visible, input[value='Найти']:visible"
        )
        submit = submit_candidates.first
        if submit_candidates.count() > 0:
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
                    submit.click()
            except Exception:
                try:
                    submit.click()
                except Exception:
                    keyword_input.press("Enter")
        else:
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
                    keyword_input.press("Enter")
            except Exception:
                keyword_input.press("Enter")

        page.wait_for_timeout(3500)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        final_url = page.url
        body_text = compact(page.locator("body").inner_text(), 30000)

        links = page.locator("a[href]")
        seen: set[str] = set()
        for i in range(min(links.count(), 3000)):
            link = links.nth(i)
            href = link.get_attribute("href") or ""
            if not href or href in seen:
                continue
            if "/tender-" not in href.lower():
                continue
            seen.add(href)
            result_links.append(
                {
                    "text": compact(link.inner_text(), 1000),
                    "href": urljoin(BASE_URL, href),
                    "class": link.get_attribute("class"),
                    "parent_html": compact(
                        link.evaluate("el => { let n=el; for(let i=0;i<6 && n;i++,n=n.parentElement){ if((n.innerText||'').length>100) return n.outerHTML; } return el.outerHTML; }"),
                        16000,
                    ),
                }
            )
            if len(result_links) >= 50:
                break

        artifact = {
            "keyword": keyword,
            "started_url": START_URL,
            "final_url": final_url,
            "time": datetime.now().isoformat(),
            "forms_before_submit": forms,
            "result_count": len(result_links),
            "results": result_links,
            "body_summary": body_text,
            "requests": requests_log,
            "responses": responses_log,
            "console": console_log,
        }
        out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        browser.close()

    print(f"B2B-Center search interaction probe completed: {out}")
    print(f"Final URL: {artifact['final_url']}")
    print(f"Result-like links: {artifact['result_count']}")
    print(f"Network requests: {len(requests_log)}")
    print(f"Network responses: {len(responses_log)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
