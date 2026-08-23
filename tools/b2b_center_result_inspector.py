"""Inspect the real result-card structure of B2B-Center modern search.

Run from project root:
    python tools/b2b_center_result_inspector.py станок

This is a diagnostic only. It does not modify production collectors.
It captures the visible result anchors from /app/next/market-search and,
for each result, prints the surrounding DOM hierarchy and text so we can
identify where B2B-Center exposes the matched lot/item text.

The report is written to both output/ (local diagnostics) and

debug_artifacts/ (so it can be committed and inspected from GitHub).
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
DEBUG_DIR = PROJECT_ROOT / "debug_artifacts"


def clean(text: str, limit: int = 5000) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit] + " ...[TRUNCATED]"


def main() -> int:
    keyword = " ".join(sys.argv[1:]).strip() or "станок"
    url = (
        f"{SEARCH_URL}?q={quote_plus(keyword)}"
        "&company_type=2&include_firm_tree=false&sort=date_desc"
        "&trade=buy&show=actual"
    )
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"b2b_result_inspector_{stamp}.txt"
    debug_output = DEBUG_DIR / f"b2b_result_inspector_{stamp}.txt"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="ru-RU")
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        links = page.locator("a[href]")
        results = []
        seen = set()

        for i in range(min(links.count(), 3000)):
            link = links.nth(i)
            href = link.get_attribute("href") or ""
            if not href or href in seen:
                continue
            if not ("/tender-" in href.lower() or "/tender/" in href.lower()):
                continue
            seen.add(href)

            data = link.evaluate(
                """
                el => {
                  const out = [];
                  let n = el;
                  for (let depth = 0; n && depth < 8; depth++, n = n.parentElement) {
                    out.push({
                      depth,
                      tag: n.tagName,
                      id: n.id || '',
                      cls: typeof n.className === 'string' ? n.className : '',
                      text: (n.innerText || '').replace(/\\s+/g, ' ').trim(),
                      html: n.outerHTML || ''
                    });
                  }
                  return out;
                }
                """
            )
            results.append((href, data))
            if len(results) >= 20:
                break

        report_parts = [
            f"URL: {url}",
            f"KEYWORD: {keyword}",
            f"TIME: {datetime.now().isoformat()}",
            f"RESULTS: {len(results)}",
            "",
        ]
        for number, (href, chain) in enumerate(results, 1):
            report_parts.append(f"===== RESULT {number} =====")
            report_parts.append(f"HREF: {href}")
            for item in chain:
                text = clean(item.get("text", ""))
                html = clean(item.get("html", ""), 12000)
                marker = "<-- KEYWORD PRESENT" if keyword.lower() in text.lower() else ""
                report_parts.append(
                    f"DEPTH={item.get('depth')} TAG={item.get('tag')} "
                    f"ID={item.get('id')!r} CLASS={item.get('cls')!r} {marker}"
                )
                report_parts.append(f"TEXT={text}")
                report_parts.append(f"HTML={html}")
                report_parts.append("")
            report_parts.append("")

        report = "\n".join(report_parts)
        output.write_text(report, encoding="utf-8")
        debug_output.write_text(report, encoding="utf-8")
        browser.close()

    print(f"B2B-Center result inspector completed: {output}")
    print(f"GitHub artifact saved: {debug_output}")
    print(f"Results inspected: {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
