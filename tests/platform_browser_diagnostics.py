from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

TARGETS = {
    "rts_tender": "https://www.rts-tender.ru/poisk/",
    "tmk": "https://zakupki.tmk-group.com/#tmk/front/index",
    "rosatom": "https://zakupki.rosatom.ru/?link=published_procurements",
}

OUT = Path("output/platform_browser_diagnostics")
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    report: dict[str, object] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="ru-RU")
        page = context.new_page()
        for name, url in TARGETS.items():
            entry: dict[str, object] = {"url": url}
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
                entry["inputs"] = page.locator("input").evaluate_all(
                    "els => els.map(e => ({type:e.type,name:e.name,placeholder:e.placeholder,aria:e.getAttribute('aria-label'),id:e.id,visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)}))"
                )
                entry["textareas"] = page.locator("textarea").evaluate_all(
                    "els => els.map(e => ({name:e.name,placeholder:e.placeholder,aria:e.getAttribute('aria-label'),id:e.id,visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)}))"
                )
                entry["buttons"] = page.locator("button").evaluate_all(
                    "els => els.map(e => ({text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),title:e.title,type:e.type,visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)})).filter(x => x.visible).slice(0,100)"
                )
                entry["links"] = page.locator("a[href]").evaluate_all(
                    "els => els.map(e => ({text:(e.innerText||'').trim().slice(0,200),href:e.href})).filter(x => x.text || x.href).slice(0,100)"
                )
                body_text = page.locator("body").inner_text(timeout=5000)
                entry["body_excerpt"] = body_text[:12000]
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            except Exception as exc:
                entry["error"] = repr(exc)
            report[name] = entry

        context.close()
        browser.close()

    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
