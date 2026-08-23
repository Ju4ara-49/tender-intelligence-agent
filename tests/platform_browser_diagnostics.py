from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

TARGETS = {
    "rts_tender": "https://www.rts-tender.ru/poisk/",
    "tmk": "https://zakupki.tmk-group.com/#tmk/front/index",
    "rosatom": "https://zakupki.rosatom.ru/?link=published_procurements",
}
QUERY = "подшипники"
OUT = Path("output/platform_browser_diagnostics")
OUT.mkdir(parents=True, exist_ok=True)

SEARCH_SELECTORS = (
    "input[type='search']",
    "input[name*='search' i]",
    "input[name*='query' i]",
    "input[name*='keyword' i]",
    "input[placeholder*='поиск' i]",
    "input[placeholder*='закуп' i]",
    "input[placeholder*='наимен' i]",
    "input[placeholder*='ключев' i]",
    "input[aria-label*='поиск' i]",
    "input[aria-label*='закуп' i]",
    "textarea[placeholder*='поиск' i]",
    "[contenteditable='true']",
)
SEARCH_LABELS = ("Найти закупку", "Поиск закупок", "Поиск", "Искать", "Найти")


def visible(locator) -> bool:
    try:
        return locator.count() > 0 and locator.is_visible()
    except Exception:
        return False


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
                value = locator.input_value() if hasattr(locator, "input_value") else query
                if value != query:
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
    return evidence


def main() -> int:
    report: dict[str, object] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="ru-RU")
        for name, url in TARGETS.items():
            page = context.new_page()
            entry: dict[str, object] = {"url": url, "query": QUERY}
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass

                entry["status"] = response.status if response else None
                entry["final_url"] = page.url
                entry["title"] = page.title()
                body_text = page.locator("body").inner_text(timeout=5000)
                entry["waf"] = "web application firewall" in body_text.lower() or "временно заблокирован" in body_text.lower()
                entry["inputs"] = page.locator("input").evaluate_all("els => els.map(e => ({type:e.type,name:e.name,placeholder:e.placeholder,aria:e.getAttribute('aria-label'),id:e.id,visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)}))")
                entry["buttons"] = page.locator("button").evaluate_all("els => els.map(e => ({text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),title:e.title,type:e.type,visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)})).filter(x => x.visible).slice(0,100)")
                entry["before_excerpt"] = body_text[:12000]

                if not entry["waf"]:
                    entry["search"] = perform_search(page, QUERY)
                    page.wait_for_timeout(5000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=7000)
                    except Exception:
                        pass
                    result_text = page.locator("body").inner_text(timeout=5000)
                    links = page.locator("a[href]").evaluate_all("els => els.map(e => ({text:(e.innerText||'').trim().slice(0,300),href:e.href})).filter(x => x.text || x.href).slice(0,200)")
                    entry["after_excerpt"] = result_text[:12000]
                    entry["result_links"] = links
                    entry["result_link_count"] = len(links)
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            except Exception as exc:
                entry["error"] = repr(exc)
            finally:
                page.close()
            report[name] = entry

        context.close()
        browser.close()

    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
