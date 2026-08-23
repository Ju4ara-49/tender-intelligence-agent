"""Create a small JSON diagnostic of real B2B-Center search result cards.

Run from project root:
    python tools/b2b_center_result_inspector_compact.py станок

The output is intentionally compact so it can be read through the GitHub
connector. It records the result URL plus text, attributes and the nearest
DOM containers that contain the keyword. This does not modify production
collectors.
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
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "debug_artifacts"


def clean(value: str, limit: int = 1200) -> str:
    value = re.sub(r"\\s+", " ", value or "").strip()
    return value if len(value) <= limit else value[:limit] + " ..."


def main() -> int:
    keyword = " ".join(sys.argv[1:]).strip() or "станок"
    url = (
        f"{SEARCH_URL}?q={quote_plus(keyword)}"
        "&company_type=2&include_firm_tree=false&sort=date_desc"
        "&trade=buy&show=actual"
    )
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"b2b_result_compact_{stamp}.json"

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
            if "/tender-" not in href.lower() and "/tender/" not in href.lower():
                continue
            seen.add(href)

            item = link.evaluate(
                """
                (el, keyword) => {
                  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                  const attrs = {};
                  for (const a of el.attributes) attrs[a.name] = a.value;
                  const chain = [];
                  let n = el;
                  for (let depth = 0; n && depth < 6; depth++, n = n.parentElement) {
                    const text = norm(n.innerText || '');
                    const low = text.toLowerCase();
                    if (low.includes(keyword.toLowerCase())) {
                      chain.push({
                        depth,
                        tag: n.tagName,
                        id: n.id || '',
                        class: typeof n.className === 'string' ? n.className : '',
                        text: text.slice(0, 1800),
                        child_count: n.children ? n.children.length : 0
                      });
                    }
                  }
                  return {
                    href: el.href || '',
                    anchor_text: norm(el.innerText || ''),
                    title: el.getAttribute('title') || '',
                    aria_label: el.getAttribute('aria-label') || '',
                    data_testid: el.getAttribute('data-testid') || '',
                    data_id: el.getAttribute('data-id') || '',
                    attributes: attrs,
                    containers_with_keyword: chain
                  };
                }
                """,
                keyword,
            )
            item["anchor_text"] = clean(item.get("anchor_text", ""))
            item["title"] = clean(item.get("title", ""), 300)
            item["aria_label"] = clean(item.get("aria_label", ""), 300)
            results.append(item)
            if len(results) >= 20:
                break

        payload = {
            "source": "B2B-Center",
            "keyword": keyword,
            "url": url,
            "time": datetime.now().isoformat(),
            "results_count": len(results),
            "results": results,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        browser.close()

    print(f"Compact B2B-Center inspection completed: {path}")
    print(f"Results inspected: {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
