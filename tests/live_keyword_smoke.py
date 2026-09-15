from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from src.collectors.registry import get_enabled_collectors
from src.settings import load_settings

KEYWORDS = ("станок", "редуктор")
PLATFORMS = ("eis", "b2b_center", "fabrikant", "rts_tender", "tmk", "rosatom")
OUT = Path("output/live_keyword_smoke")
OUT.mkdir(parents=True, exist_ok=True)


def run_one(collector, keyword: str) -> dict:
    started = time.monotonic()
    try:
        results = collector.search([keyword], since=None) or []
        return {
            "platform": collector.platform,
            "keyword": keyword,
            "status": "ok",
            "count": len(results),
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "samples": [
                {
                    "external_id": t.external_id,
                    "title": t.title,
                    "url": t.url,
                }
                for t in list(results)[:10]
            ],
        }
    except Exception as exc:
        return {
            "platform": collector.platform,
            "keyword": keyword,
            "status": "exception",
            "count": 0,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
            "samples": [],
        }


def main() -> int:
    settings = load_settings()
    collectors = get_enabled_collectors(settings.config, enabled_platforms=list(PLATFORMS))
    found = {c.platform for c in collectors}
    missing = sorted(set(PLATFORMS) - found)
    results = []
    with ThreadPoolExecutor(max_workers=len(collectors) or 1) as pool:
        futures = [
            pool.submit(run_one, collector, keyword)
            for collector in collectors
            for keyword in KEYWORDS
        ]
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda x: (x["platform"], x["keyword"]))
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "keywords": list(KEYWORDS),
        "platforms": list(PLATFORMS),
        "missing_collectors": missing,
        "results": results,
    }
    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for item in results:
        print(
            f'{item["platform"]} | {item["keyword"]} | '
            f'{item["status"]} | {item["count"]} | {item["elapsed_seconds"]}s'
        )
        for sample in item["samples"][:3]:
            print(f'  {sample["external_id"]}: {sample["title"][:180]}')
    if missing:
        print("MISSING COLLECTORS:", ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
