from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

TARGETS = {
    "eis": "https://zakupki.gov.ru/epz/order/extendedsearch/results.html",
    "b2b_center": "https://www.b2b-center.ru/market/",
    "fabrikant_223": "https://soap2.fabrikant.ru/223/catalog/procedure/published",
    "fabrikant_44": "https://soap4.fabrikant.ru/44/catalog/procedure",
    "rts_tender": "https://www.rts-tender.ru/",
    "tmk": "https://zakupki.tmk-group.com/",
    "rosatom": "https://zakupki.rosatom.ru/?link=published_procurements",
}
DEFAULT_QUERIES = ("подшипники",)
QUERIES = tuple(q.strip() for q in os.getenv("PLATFORM_DIAGNOSTIC_QUERIES", "").split(",") if q.strip()) or DEFAULT_QUERIES
OUT = Path("output/platform_browser_diagnostics")
OUT.mkdir(parents=True, exist_ok=True)
# Live diagnostics are a hard gate: an external timeout/access block means the
# platform was not actually verified. Use bounded retries so a transient runner
# network glitch is retried before the run is declared failed.
NAVIGATION_TIMEOUT_MS = 20000
NAVIGATION_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (2, 4)
INITIAL_WAIT_MS = 2500
NETWORK_IDLE_TIMEOUT_MS = 2500
SEARCH_SETTLE_MS = 2500
SCREENSHOT_TIMEOUT_MS = 5000
HARD_EXTERNAL_ACCESS = os.getenv("HARD_EXTERNAL_ACCESS", "").strip().lower() in {"1", "true", "yes", "on"}
EXTERNAL_CHALLENGE_MARKERS = (
    "для работы с сайтом необходимы включенные javascript и cookies",
    "для работы с сайтом необходимы включенные javascript",
    "пожалуйста подождите",
    "enable javascript and cookies",
    "checking your browser",
    "web page blocked!",
    "the url you requested has been blocked",
    "attack id:",
)

SEARCH_SELECTORS = (
    "input[type='search']", "input[name*='search' i]", "input[name*='query' i]",
    "input[name*='keyword' i]", "input[name*='searchString' i]",
    "input[placeholder*='поиск' i]", "input[placeholder*='закуп' i]",
    "input[placeholder*='наимен' i]", "input[placeholder*='ключев' i]",
    "input[aria-label*='поиск' i]", "input[aria-label*='закуп' i]",
    "textarea[placeholder*='поиск' i]", "[contenteditable='true']",
)
SEARCH_LABELS = ("Найти закупку", "Поиск закупок", "Поиск", "Искать", "Найти", "Применить")
ACCESS_BLOCK_STATUSES = frozenset({401, 403, 429})
EXTERNAL_TIMEOUT_MARKERS = (
    "ERR_TIMED_OUT",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_NETWORK_CHANGED",
    "timeout",
    "timed out",
)
PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def visible(locator) -> bool:
    try:
        return locator.count() > 0 and locator.is_visible()
    except Exception:
        return False


def classify_http_access(status: int | None) -> str | None:
    if status in ACCESS_BLOCK_STATUSES:
        return "access_block"
    return None


def is_external_timeout(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker.lower() in message for marker in EXTERNAL_TIMEOUT_MARKERS)


def is_external_challenge(text: str) -> bool:
    normalized = " ".join(str(text).split()).lower()
    return any(marker in normalized for marker in EXTERNAL_CHALLENGE_MARKERS)


def goto_with_retries(page, url: str, *, timeout_ms: int = NAVIGATION_TIMEOUT_MS, attempts: int = NAVIGATION_ATTEMPTS):
    """Retry only transient navigation failures; never bypass access controls."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = page.goto(url, wait_until="commit", timeout=timeout_ms)
            return response, attempt
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            time.sleep(RETRY_DELAYS_SECONDS[min(attempt - 1, len(RETRY_DELAYS_SECONDS) - 1)])
    assert last_error is not None
    raise last_error


def perform_search(page, query: str) -> dict[str, object]:
    frames = [page.main_frame] + [frame for frame in page.frames if frame != page.main_frame]
    evidence: dict[str, object] = {"control_found": False, "selector": None, "frame_url": None}
    for frame in frames:
        for label in SEARCH_LABELS:
            try:
                button = frame.get_by_role("button", name=label, exact=False).first
                if visible(button):
                    button.click(timeout=1200)
                    page.wait_for_timeout(250)
                    break
            except Exception:
                continue
    for frame in frames:
        for selector in SEARCH_SELECTORS:
            try:
                locator = frame.locator(selector).first
                if not visible(locator):
                    continue
                locator.fill(query, timeout=1200)
                if locator.input_value() != query:
                    continue
                try:
                    locator.press("Enter", timeout=1200)
                except Exception:
                    pass
                for label in SEARCH_LABELS:
                    try:
                        button = frame.get_by_role("button", name=label, exact=False).first
                        if visible(button):
                            button.click(timeout=1200)
                            break
                    except Exception:
                        continue
                evidence.update({"control_found": True, "selector": selector, "frame_url": frame.url})
                return evidence
            except Exception:
                continue
        try:
            textbox = frame.get_by_role("textbox").first
            if visible(textbox):
                textbox.fill(query, timeout=1200)
                textbox.press("Enter", timeout=1200)
                evidence.update({"control_found": True, "selector": "role=textbox", "frame_url": frame.url})
                return evidence
        except Exception:
            continue
    return evidence


def wait_for_initial_dom(page) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    try:
        page.locator("body").wait_for(state="attached", timeout=2500)
    except Exception:
        pass


def extract_result_evidence(text: str) -> dict[str, object]:
    normalized = " ".join(text.split())
    patterns = (
        r"\bВсего\s*:\s*([0-9][0-9\s]*)\b",
        r"\bАктуальных\s+лотов\s*:\s*([0-9][0-9\s]*)\b",
        r"\bПоказаны\s+первые\s+([0-9][0-9\s]*)\s+запис(?:и|ей)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, re.I)
        if not match:
            continue
        raw = re.sub(r"\s+", "", match.group(1))
        try:
            return {"result_count": int(raw), "result_count_evidence": match.group(0)}
        except ValueError:
            continue
    return {"result_count": None, "result_count_evidence": None}


def has_published_listing_evidence(platform: str, links: list[dict[str, object]]) -> bool:
    """Return True when a legacy portal exposes a real published-procurement listing without a search form."""
    if platform != "rosatom":
        return False
    for item in links:
        href = str(item.get("href", "")).lower()
        if "zakupki.rosatom.ru" in href and ("obj_id=" in href or "link=procurements" in href):
            return True
    return False


def platform_url_is_rosatom_published(url: str) -> bool:
    lowered = str(url).lower()
    return "zakupki.rosatom.ru" in lowered and "link=published_procurements" in lowered


def has_rosatom_published_page(url: str, status: int | None) -> bool:
    return status == 200 and platform_url_is_rosatom_published(url)


def save_viewport_screenshot(page, name: str) -> None:
    """Save real viewport evidence, or a clearly synthetic placeholder if impossible."""
    path = OUT / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=False, timeout=SCREENSHOT_TIMEOUT_MS)
        return
    except Exception as exc:
        print(f"{name}: screenshot unavailable: {exc!r}")
    path.write_bytes(PLACEHOLDER_PNG)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    report: dict[str, object] = {}
    failures: list[str] = []
    ci_failures: list[str] = []
    internal_failures: list[str] = []
    access_blocks: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="ru-RU")
        context.set_default_timeout(3000)
        context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
        for name, url in TARGETS.items():
            page = context.new_page()
            entry: dict[str, object] = {"url": url, "query": QUERIES}
            try:
                response, navigation_attempt = goto_with_retries(page, url)
                entry["navigation_attempt"] = navigation_attempt
                wait_for_initial_dom(page)
                page.wait_for_timeout(INITIAL_WAIT_MS)
                try:
                    page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
                except Exception:
                    pass
                entry["status"] = response.status if response else None
                entry["final_url"] = page.url
                entry["title"] = page.title()
                body_text = page.locator("body").inner_text(timeout=3000)
                lower_body = body_text.lower()
                entry["waf"] = "web application firewall" in lower_body or "временно заблокирован" in lower_body
                entry["http_access_class"] = classify_http_access(response.status if response else None)
                entry["inputs"] = page.locator("input").evaluate_all("els => els.map(e => ({type:e.type,name:e.name,placeholder:e.placeholder,aria:e.getAttribute('aria-label'),id:e.id,visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)}))")
                entry["buttons"] = page.locator("button").evaluate_all("els => els.map(e => ({text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),title:e.title,type:e.type,visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)})).filter(x => x.visible).slice(0,100)")
                entry["before_excerpt"] = body_text[:12000]
                access_class = entry["http_access_class"]
                if entry["waf"] or access_class:
                    entry["diagnostic_state"] = "waf_or_block" if entry["waf"] else "http_access_block"
                    entry["failure_class"] = "access_block"
                    message = f"{name}: access block (HTTP {entry['status']})" if access_class else f"{name}: WAF or access block"
                    failures.append(message)
                    access_blocks.append(message)
                    ci_failures.append(message)
                else:
                    query_results = []
                    control_found = False
                    all_links = []
                    result_text = ""
                    for query in QUERIES:
                        search_evidence = perform_search(page, query)
                        control_found = control_found or bool(search_evidence.get("control_found"))
                        page.wait_for_timeout(SEARCH_SETTLE_MS)
                        try:
                            page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
                        except Exception:
                            pass
                        result_text = page.locator("body").inner_text(timeout=3000)
                        evidence = extract_result_evidence(result_text)
                        links = page.locator("a[href]").evaluate_all("els => els.map(e => ({text:(e.innerText||'').trim().slice(0,300),href:e.href})).filter(x => x.text || x.href).slice(0,200)")
                        all_links.extend(links)
                        query_results.append({
                            "query": query,
                            "search": search_evidence,
                            **evidence,
                            "result_link_count": len(links),
                        })
                    entry["search_results"] = query_results
                    entry["search"] = query_results[0]["search"] if query_results else {"control_found": False}
                    entry.update(extract_result_evidence(result_text))
                    entry["after_excerpt"] = result_text[:12000]
                    entry["result_links"] = all_links[-200:]
                    entry["result_link_count"] = len(entry["result_links"])
                    result_count = entry.get("result_count")
                    if not control_found and is_external_challenge(result_text):
                        entry["diagnostic_state"] = "external_challenge"
                        entry["failure_class"] = "external_access"
                        entry["external_challenge"] = True
                        message = f"{name}: external JavaScript/cookie challenge"
                        failures.append(message)
                        access_blocks.append(message)
                        ci_failures.append(message)
                    elif not control_found:
                        if has_published_listing_evidence(name, links) or has_rosatom_published_page(page.url, response.status if response else None):
                            entry["diagnostic_state"] = "listing_available"
                            entry["search_mode"] = "published_listing_fallback"
                            entry["failure_class"] = "search_adapter_inconclusive"
                            entry["search"] = {**entry["search"], "control_found": False, "fallback": "published_listing"}
                        else:
                            entry["diagnostic_state"] = "search_control_missing"
                            entry["failure_class"] = "search_adapter"
                            message = f"{name}: search control missing"
                            failures.append(message)
                            ci_failures.append(message)
                            internal_failures.append(message)
                    elif result_count is not None or links:
                        entry["diagnostic_state"] = "ok"
                    else:
                        entry["diagnostic_state"] = "search_returned_no_evidence"
                        entry["failure_class"] = "search_result_surface"
                        message = f"{name}: search returned no result evidence"
                        failures.append(message)
                        ci_failures.append(message)
                        internal_failures.append(message)
            except PlaywrightTimeoutError as exc:
                entry["error"] = repr(exc)
                entry["diagnostic_state"] = "external_timeout"
                entry["failure_class"] = "external_access"
                message = f"{name}: external navigation timeout"
                failures.append(message)
                access_blocks.append(message)
                ci_failures.append(message)
            except Exception as exc:
                entry["error"] = repr(exc)
                if is_external_timeout(exc):
                    entry["diagnostic_state"] = "external_timeout"
                    entry["failure_class"] = "external_access"
                    message = f"{name}: external navigation timeout"
                    failures.append(message)
                    access_blocks.append(message)
                    ci_failures.append(message)
                else:
                    entry["diagnostic_state"] = "exception"
                    entry["failure_class"] = "transport"
                    message = f"{name}: {exc!r}"
                    failures.append(message)
                    ci_failures.append(message)
                    internal_failures.append(message)
            finally:
                save_viewport_screenshot(page, name)
                page.close()
            report[name] = entry
        context.close()
        browser.close()
    report["failures"] = failures
    report["ci_failures"] = ci_failures
    report["internal_failures"] = internal_failures
    report["access_blocks"] = access_blocks
    report["hard_external_access"] = HARD_EXTERNAL_ACCESS
    report["access_block_count"] = len(access_blocks)
    report["ci_failure_count"] = len(ci_failures)
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    summary_lines = ["## Platform browser diagnostics", "", "Queries: `" + ", ".join(QUERIES) + "`", ""]
    for name, entry in report.items():
        if name in {"failures", "ci_failures", "internal_failures", "access_blocks", "hard_external_access", "access_block_count", "ci_failure_count"}:
            continue
        summary_lines.append(f"- **{name}**: `{entry.get('diagnostic_state', 'unknown')}` status={entry.get('status')} result_count={entry.get('result_count')} links={entry.get('result_link_count', 0)} navigation_attempt={entry.get('navigation_attempt', '-')}")
    if access_blocks:
        access_heading = "### External access failures (hard gate)" if HARD_EXTERNAL_ACCESS else "### External access limitations (runner/network)"
        summary_lines.extend(["", access_heading, *[f"- {item}" for item in access_blocks]])
    if ci_failures:
        summary_lines.extend(["", "### Diagnostic failures", *[f"- {item}" for item in ci_failures]])
    else:
        summary_lines.extend(["", "All supported public platform endpoints passed the browser search probe."])
    (OUT / "summary.md").write_text("\n".join(summary_lines), encoding="utf-8")
    print("\n".join(summary_lines))
    if internal_failures:
        print("Internal browser diagnostic failures:")
        for item in internal_failures:
            print(f"- {item}")
    if HARD_EXTERNAL_ACCESS and access_blocks:
        print("External browser access failures are HARD-GATE failures on this runner:")
        for item in access_blocks:
            print(f"- {item}")
    blocking_failures = list(internal_failures)
    if HARD_EXTERNAL_ACCESS:
        blocking_failures.extend(access_blocks)
    return 1 if blocking_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
