from __future__ import annotations

import json
import os
from pathlib import Path

from src.collectors.tenderguru_fallback import search as tenderguru_search

TARGETS = {
    "eis": "eis",
    "b2b_center": "b2b_center",
    "fabrikant_223": "fabrikant",
    "fabrikant_44": "fabrikant",
    "rts_tender": "rts_tender",
    "tmk": "tmk",
    "rosatom": "rosatom",
}
QUERIES = tuple(value.strip() for value in os.getenv("PLATFORM_DIAGNOSTIC_QUERIES", "станок,подшипник,лебедка").split(",") if value.strip())
OUT = Path("output/platform_keyword_fallback_diagnostics")
OUT.mkdir(parents=True, exist_ok=True)


def _matches(text: str, query: str) -> bool:
    normalized = text.casefold().replace("ё", "е")
    query = query.casefold().replace("ё", "е")
    if query in normalized:
        return True
    groups = {
        "станок": ("станка", "станки", "станков", "станкам", "станками", "станке", "станком"),
        "подшипник": ("подшипника", "подшипники", "подшипников", "подшипнику", "подшипникам", "подшипником", "подшипниками", "подшипнике", "подшипниках"),
        "лебедка": ("лебедки", "лебедку", "лебедкой", "лебедкою", "лебедок", "лебедкам", "лебедками"),
    }
    for canonical, forms in groups.items():
        if query == canonical or query in forms:
            return any(form in normalized for form in (canonical, *forms))
    return False


def main() -> int:
    report: dict[str, object] = {"targets": {}, "queries": list(QUERIES)}
    failures: list[str] = []
    for target, logical_platform in TARGETS.items():
        target_report: dict[str, object] = {}
        for query in QUERIES:
            try:
                results = tenderguru_search(platform=logical_platform, keyword=query, timeout=20, max_pages=1, max_results=25)
                matched = [item for item in results if _matches(" ".join((item.title or "", item.description or "")), query)]
                target_report[query] = {"count": len(results), "keyword_matches": len(matched), "platform": logical_platform}
                if not matched:
                    failures.append(f"{target}/{query}: no keyword-matching fallback result")
            except Exception as exc:
                target_report[query] = {"error": f"{type(exc).__name__}: {exc}"}
                failures.append(f"{target}/{query}: {type(exc).__name__}: {exc}")
        report["targets"][target] = target_report

    report["failures"] = failures
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        print("Platform keyword fallback diagnostics FAILED:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"Platform keyword fallback diagnostics PASS: {len(TARGETS)} targets × {len(QUERIES)} queries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
