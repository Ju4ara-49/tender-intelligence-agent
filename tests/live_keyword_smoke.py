from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from src.collectors.registry import get_enabled_collectors
from src.models.tender import Tender
from src.settings import load_settings

KEYWORDS = ("станок", "подшипник", "лебедка")
PLATFORMS = ("eis", "b2b_center", "fabrikant", "rts_tender", "tmk", "rosatom")
OUT = Path("output/live_keyword_smoke")
OUT.mkdir(parents=True, exist_ok=True)


def validate_search_contract(results: list[Tender]) -> dict:
    """Acceptance contract: every search result must have external_id and url."""
    violations = []
    for i, t in enumerate(results):
        if not t.external_id:
            violations.append(f"result[{i}].external_id is empty")
        if not t.url:
            violations.append(f"result[{i}].url is empty")
    return {
        "total": len(results),
        "contract_violations": violations,
        "passed": len(violations) == 0,
    }


def probe_details(collector, results: list[Tender], limit: int = 3) -> dict:
    """Acceptance contract: get_details must return a Tender with title when URL present."""
    detail_reports = []
    candidates = [t for t in results if t.url and t.external_id][:limit]
    for cand in candidates:
        started = time.monotonic()
        try:
            detail = collector.get_details(cand.external_id)
            ok = detail is not None and (detail.title or "").strip() != ""
            detail_reports.append({
                "external_id": cand.external_id,
                "ok": ok,
                "elapsed_seconds": round(time.monotonic() - started, 2),
            })
        except Exception as exc:
            detail_reports.append({
                "external_id": cand.external_id,
                "ok": False,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "error": f"{type(exc).__name__}: {exc}",
            })
    return {
        "probed": len(detail_reports),
        "passed": sum(1 for d in detail_reports if d["ok"]),
        "details": detail_reports,
    }


def run_one(collector, keyword: str) -> dict:
    started = time.monotonic()
    try:
        results = collector.search([keyword], since=None) or []
        search_contract = validate_search_contract(results)
        detail_result = probe_details(collector, results) if search_contract["passed"] else {"probed": 0, "passed": 0, "skipped": "search contract failed"}
        return {
            "platform": collector.platform,
            "keyword": keyword,
            "status": "ok",
            "count": len(results),
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "search_contract": search_contract,
            "details": detail_result,
            "samples": [
                {
                    "external_id": t.external_id,
                    "title": t.title,
                    "url": t.url,
                    "published_at": t.published_at.isoformat() if t.published_at else None,
                }
                for t in list(results)[:10]
            ],
        }
    except Exception as exc:
        return {
            "platform": collector.platform,
            "keyword": keyword,
            "status": "external_unavailable" if type(exc).__name__ == "CollectorUnavailableError" else "exception",
            "count": 0,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "search_contract": {"total": 0, "contract_violations": [], "passed": False, "skipped": "search failed"},
            "details": {"probed": 0, "passed": 0, "skipped": "search failed"},
            "error": f"{type(exc).__name__}: {exc}",
            "samples": [],
        }


def run_platform(collector) -> list[dict]:
    """Probe one collector sequentially so its mutable parser state is isolated.

    Several collectors intentionally retain state between discovery and detail
    parsing (URLs, titles, active Fabrikant host, authenticated session). The
    previous smoke test submitted three keywords against the same instance from
    different worker threads, creating a race that could manufacture failures
    which never occur in the real orchestrator. Parallelize by platform, not by
    keyword, and keep each collector's keyword probes sequential.
    """
    return [run_one(collector, keyword) for keyword in KEYWORDS]


def main() -> int:
    settings = load_settings()
    collectors = get_enabled_collectors(settings.config, enabled_platforms=list(PLATFORMS))
    found = {c.platform for c in collectors}
    missing = sorted(set(PLATFORMS) - found)
    results = []
    with ThreadPoolExecutor(max_workers=len(collectors) or 1) as pool:
        futures = [pool.submit(run_platform, collector) for collector in collectors]
        for future in as_completed(futures):
            results.extend(future.result())

    results.sort(key=lambda x: (x["platform"], x["keyword"]))
    summary = {
        "search_contract_passes": sum(1 for r in results if r.get("search_contract", {}).get("passed")),
        "search_contract_total": len(results),
        "detail_passes": sum(r.get("details", {}).get("passed", 0) for r in results),
        "detail_probes": sum(r.get("details", {}).get("probed", 0) for r in results),
    }
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "keywords": list(KEYWORDS),
        "platforms": list(PLATFORMS),
        "missing_collectors": missing,
        "summary": summary,
        "results": results,
    }
    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for item in results:
        sc = item.get("search_contract", {})
        dt = item.get("details", {})
        print(
            f'{item["platform"]} | {item["keyword"]} | '
            f'{item["status"]} | {item["count"]} | {item["elapsed_seconds"]}s | '
            f'contract={"✓" if sc.get("passed") else "✗"} | '
            f'details={dt.get("passed",0)}/{dt.get("probed",0)}'
        )
        for sample in item["samples"][:3]:
            print(f'  {sample["external_id"]}: {sample["title"][:180]}')

    failures = [item for item in results if item["status"] == "exception"]
    contract_fails = [item for item in results if not item.get("search_contract", {}).get("passed")]
    if missing or failures or contract_fails:
        if missing:
            print(f"\nMISSING COLLECTORS: {', '.join(missing)}")
        if failures:
            print(f"\nUNEXPECTED COLLECTOR ERRORS: {json.dumps(failures, ensure_ascii=False)}")
        if contract_fails:
            print(f"\nSEARCH CONTRACT VIOLATIONS ({len(contract_fails)}):")
            for item in contract_fails:
                sc = item.get("search_contract", {})
                print(f"  {item['platform']} | {item['keyword']}: {sc.get('contract_violations', [])}")
        return 1
    print(f"\nSUMMARY: {summary['search_contract_passes']}/{summary['search_contract_total']} platforms passed search contract | "
          f"{summary['detail_passes']}/{summary['detail_probes']} detail probes succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
