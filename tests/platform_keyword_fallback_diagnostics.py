from __future__ import annotations

import json
import os
from pathlib import Path

from src.collectors.tenderguru_fallback import search as tenderguru_search

PLATFORMS = (
    "eis",
    "b2b_center",
    "fabrikant",
    "rts_tender",
    "tmk",
    "rosatom",
)
QUERIES = tuple(
    value.strip()
    for value in os.getenv("PLATFORM_DIAGNOSTIC_QUERIES", "станок,подшипник,лебедка").split(",")
    if value.strip()
)
OUT = Path("output/platform_keyword_fallback_diagnostics")
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    report: dict[str, object] = {"platforms": {}, "queries": list(QUERIES)}
    failures: list[str] = []
    for platform in PLATFORMS:
        platform_report: dict[str, object] = {}
        for query in QUERIES:
            try:
                results = tenderguru_search(
                    platform=platform,
                    keyword=query,
                    timeout=20,
                    max_pages=1,
                    max_results=25,
                )
                matched = [
                    item
                    for item in results
                    if query.casefold().replace("ё", "е")
                    in " ".join((item.title or "", item.description or "")).casefold().replace("ё", "е")
                    or any(
                        form.casefold().replace("ё", "е")
                        in " ".join((item.title or "", item.description or "")).casefold().replace("ё", "е")
                        for form in {
                            "станок": ("станка", "станки", "станков", "станкам", "станками", "станке", "станком"),
                            "подшипник": ("подшипника", "подшипники", "подшипников", "подшипнику", "подшипникам", "подшипником", "подшипниками", "подшипнике", "подшипниках"),
                            "лебедка": ("лебедки", "лебедку", "лебедкой", "лебедкою", "лебедок", "лебедкам", "лебедками"),
                        }.get(query.casefold().replace("ё", "е"), ())
                    )
                ]
                platform_report[query] = {"count": len(results), "keyword_matches": len(matched)}
                if not matched:
                    failures.append(f"{platform}/{query}: no keyword-matching fallback result")
            except Exception as exc:
                platform_report[query] = {"error": f"{type(exc).__name__}: {exc}"}
                failures.append(f"{platform}/{query}: {type(exc).__name__}: {exc}")
        report["platforms"][platform] = platform_report

    report["failures"] = failures
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        print("Platform keyword fallback diagnostics FAILED:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"Platform keyword fallback diagnostics PASS: {len(PLATFORMS)} platforms × {len(QUERIES)} queries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
