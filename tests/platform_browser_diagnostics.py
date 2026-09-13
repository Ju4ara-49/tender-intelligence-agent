from __future__ import annotations

import json
import multiprocessing as mp
import queue as queue_module
import re
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
QUERY = "подшипники"
OUT = Path("output/platform_browser_diagnostics")
OUT.mkdir(parents=True, exist_ok=True)
NAVIGATION_TIMEOUT_MS = 30000
NAVIGATION_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (2, 5)
TARGET_TIMEOUT_SECONDS = 150

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


def probe_target(name: str, url: str) -> tuple[str, dict[str, object], list[str], list[str], list[str]]:
    """Run one target in an isolated Playwright process."""
    entry: dict[str, object] = {"url": url, "query": QUERY}
    failures: list[str] = []
    ci_failures: list[str] = []
    access_blocks: list[str] = []
    page = None
    browser = None
    context = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(locale="ru-RU")
            context.set_default_timeout(5000)
            context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
            page = context.new_page()
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
                    message = f"{name}: access block (HTTP {entry['status']})" if access_class else f"{name}: WAF or access block"
                    failures.append(message)
                    access_blocks.append(message)
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
                        message = f"{name}: search control missing"
                        failures.append(message)
                        ci_failures.append(message)
                    elif result_count is not None or links:
                        entry["diagnostic_state"] = "ok"
                    else:
                        entry["diagnostic_state"] = "search_returned_no_evidence"
                        entry["failure_class"] = "search_result_surface"
                        message = f"{name}: search returned no result evidence"
                        failures.append(message)
                        ci_failures.append(message)
            except PlaywrightTimeoutError as exc:
                entry["error"] = repr(exc)
                entry["diagnostic_state"] = "external_timeout"
                entry["failure_class"] = "external_access"
                message = f"{name}: external navigation timeout"
                failures.append(message)
                access_blocks.append(message)
            except Exception as exc:
                entry["error"] = repr(exc)
                entry["diagnostic_state"] = "exception"
                entry["failure_class"] = "transport"
                message = f"{name}: {exc!r}"
                failures.append(message)
                ci_failures.append(message)
            finally:
                if page is not None:
                    try:
                        page.screenshot(path=str(OUT / f"{name}.png"), full_page=False, timeout=10000)
                        entry["screenshot_created"] = True
                    except Exception as exc:
                        entry["screenshot_created"] = False
                        entry["screenshot_error"] = repr(exc)
                if context is not None:
                    context.close()
                if browser is not None:
                    browser.close()
    except Exception as exc:
        entry["error"] = repr(exc)
        entry["diagnostic_state"] = "browser_exception"
        entry["failure_class"] = "transport"
        message = f"{name}: {exc!r}"
        failures.append(message)
        ci_failures.append(message)
    return name, entry, failures, ci_failures, access_blocks


def _probe_worker(name: str, url: str, queue) -> None:
    try:
        queue.put(probe_target(name, url))
    except Exception as exc:
        queue.put((name, {"url": url, "query": QUERY, "diagnostic_state": "worker_exception", "error": repr(exc)}, [f"{name}: {exc!r}"], [f"{name}: {exc!r}"], []))


def main() -> int:
    report: dict[str, object] = {}
    failures: list[str] = []
    ci_failures: list[str] = []
    access_blocks: list[str] = []

    # Start all probes together and enforce one global wall-clock budget. The
    # parent drains the queue while children run; otherwise a large diagnostic
    # payload can fill the IPC pipe and keep a completed child alive forever.
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    processes = {
        name: ctx.Process(target=_probe_worker, args=(name, url, result_queue), name=f"platform-probe-{name}")
        for name, url in TARGETS.items()
    }
    for process in processes.values():
        process.daemon = True
        process.start()

    received: set[str] = set()
    deadline = time.monotonic() + TARGET_TIMEOUT_SECONDS
    while processes and time.monotonic() < deadline:
        while True:
            try:
                name, entry, target_failures, target_ci_failures, target_access_blocks = result_queue.get_nowait()
            except queue_module.Empty:
                break
            if name in received:
                continue
            received.add(name)
            report[name] = entry
            failures.extend(target_failures)
            ci_failures.extend(target_ci_failures)
            access_blocks.extend(target_access_blocks)

        finished = [name for name, process in processes.items() if not process.is_alive()]
        for name in finished:
            processes[name].join(timeout=1)
            del processes[name]
        if processes:
            time.sleep(0.2)

    for name, process in list(processes.items()):
        process.terminate()
        process.join(5)
        report[name] = {
            "url": TARGETS[name],
            "query": QUERY,
            "diagnostic_state": "external_timeout",
            "failure_class": "external_access",
            "error": f"target exceeded hard timeout of {TARGET_TIMEOUT_SECONDS}s",
            "screenshot_created": False,
        }
        message = f"{name}: external navigation timeout"
        failures.append(message)
        access_blocks.append(message)

    while True:
        try:
            name, entry, target_failures, target_ci_failures, target_access_blocks = result_queue.get_nowait()
        except queue_module.Empty:
            break
        if name in received:
            continue
        received.add(name)
        report[name] = entry
        failures.extend(target_failures)
        ci_failures.extend(target_ci_failures)
        access_blocks.extend(target_access_blocks)

    for name in TARGETS:
        report.setdefault(name, {
            "url": TARGETS[name],
            "query": QUERY,
            "diagnostic_state": "missing",
            "failure_class": "transport",
            "screenshot_created": False,
        })
        if report[name].get("diagnostic_state") == "missing":
            message = f"{name}: probe produced no result"
            failures.append(message)
            ci_failures.append(message)

    ordered_report = {name: report[name] for name in TARGETS}
    ordered_report["failures"] = failures
    ordered_report["ci_failures"] = ci_failures
    ordered_report["access_blocks"] = access_blocks
    ordered_report["access_block_count"] = len(access_blocks)
    ordered_report["ci_failure_count"] = len(ci_failures)
    (OUT / "report.json").write_text(json.dumps(ordered_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(ordered_report, ensure_ascii=False, indent=2))

    summary_lines = ["## Platform browser diagnostics", "", f"Query: `{QUERY}`", ""]
    for name in TARGETS:
        entry = ordered_report[name]
        summary_lines.append(f"- **{name}**: `{entry.get('diagnostic_state', 'unknown')}` status={entry.get('status')} result_count={entry.get('result_count')} links={entry.get('result_link_count', 0)} navigation_attempt={entry.get('navigation_attempt', '-')}")
    if access_blocks:
        summary_lines.extend(["", "### External access blocks / timeouts (inconclusive, not a Python failure)", *[f"- {item}" for item in access_blocks]])
    if ci_failures:
        summary_lines.extend(["", "### Diagnostic failures", *[f"- {item}" for item in ci_failures]])
    elif not access_blocks:
        summary_lines.extend(["", "All supported public platform endpoints passed the browser search probe."])
    else:
        summary_lines.extend(["", "No internal diagnostic failure was detected; externally unreachable portals require a network-accessible recheck."])
    (OUT / "summary.md").write_text("\n".join(summary_lines), encoding="utf-8")
    print("\n".join(summary_lines))
    return 1 if ci_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())