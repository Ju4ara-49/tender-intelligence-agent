from __future__ import annotations

import json
import re
import time
from pathlib import Path

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
QUERY = "подшипники"
OUT = Path("output/platform_browser_diagnostics")
OUT.mkdir(parents=True, exist_ok=True)
NAVIGATION_TIMEOUT_MS = 30000
NAVIGATION_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (2, 5)

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


def visible(locator) -> bool:
    try:
        return locator.count() > 0 and locator.is_visible()
    except Exception:
        return False


def classify_http_access(status: int | None) -> str | None:
    if status in ACCESS_BLOCK_STATUSES:
        return "access_block"
    return None


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
                    button.click(timeout=2000)
                    page.wait_for_timeout(700)
                    break
            except Exception:
                continue
    for frame in frames:
        for selector in SEARCH_SELECTORS:
            try:
                locator = frame.locator(selector).first
                if not visible(locator):
                    continue
                locator.fill(query)
                if locator.input_value() != query:
                    continue
                try:
                    locator.press("Enter")
                except Exception:
                    pass
                for label in SEARCH_LABELS:
                    try:
                        button = frame.get_by_role("button", name=label, exact=False).first
                        if visible(button):
                            button.click(timeout=2000)
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
                textbox.fill(query)
                textbox.press("Enter")
                evidence.update({"control_found": True, "selector": "role=textbox", "frame_url": frame.url})
                return evidence
        except Exception:
            continue
    return evidence


def wait_for_initial_dom(page) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    try:
        page.locator("body").wait_for(state="attached", timeout=5000)
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


def main() -> int:
    report: dict[str, object] = {}
    failures: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="ru-RU")
        for name, url in TARGETS.items():
            page = context.new_page()
            entry: dict[str, object] = {"url": url, "query": QUERY}
            try:
                response, navigation_attempt = goto_with_retries(page, url)
                entry["navigation_attempt"] = navigation_attempt
                wait_for_initial_dom(page)
                page.wait_for_timeout(5000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                entry["status"] = response.status if response else None
                entry["final_url"] = page.url
                entry["title"] = page.title()
                body_text = page.locator("body").inner_text(timeout=5000)
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
                    failures.append(f"{name}: access block (HTTP {entry['status']})" if access_class else f"{name}: WAF or access block")
                else:
                    entry["search"] = perform_search(page, QUERY)
                    page.wait_for_timeout(5000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=7000)
                    except Exception:
                        pass
                    result_text = page.locator("body").inner_text(timeout=5000)
                    entry.update(extract_result_evidence(result_text))
                    links = page.locator("a[href]").evaluate_all("els => els.map(e => ({text:(e.innerText||'').trim().slice(0,300),href:e.href})).filter(x => x.text || x.href).slice(0,200)")
                    entry["after_excerpt"] = result_text[:12000]
                    entry["result_links"] = links
                    entry["result_link_count"] = len(links)
                    control_found = bool(entry["search"].get("control_found"))
                    result_count = entry.get("result_count")
                    if not control_found:
                        entry["diagnostic_state"] = "search_control_missing"
                        entry["failure_class"] = "search_adapter"
                        failures.append(f"{name}: search control missing")
                    elif result_count is not None or links:
                        entry["diagnostic_state"] = "ok"
                    else:
                        entry["diagnostic_state"] = "search_returned_no_evidence"
                        entry["failure_class"] = "search_result_surface"
                        failures.append(f"{name}: search returned no result evidence")
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            except Exception as exc:
                entry["error"] = repr(exc)
                entry["diagnostic_state"] = "exception"
                entry["failure_class"] = "transport"
                failures.append(f"{name}: {exc!r}")
            finally:
                page.close()
            report[name] = entry
        context.close()
        browser.close()
    report["failures"] = failures
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    summary_lines = ["## Platform browser diagnostics", "", f"Query: `{QUERY}`", ""]
    for name, entry in report.items():
        if name == "failures":
            continue
        summary_lines.append(f"- **{name}**: `{entry.get('diagnostic_state', 'unknown')}` status={entry.get('status')} result_count={entry.get('result_count')} links={entry.get('result_link_count', 0)} navigation_attempt={entry.get('navigation_attempt', '-')}")
    if failures:
        summary_lines.extend(["", "### Failures", *[f"- {item}" for item in failures]])
    else:
        summary_lines.extend(["", "All supported public platform endpoints passed the browser search probe."])
    (OUT / "summary.md").write_text("\n".join(summary_lines), encoding="utf-8")
    print("\n".join(summary_lines))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
