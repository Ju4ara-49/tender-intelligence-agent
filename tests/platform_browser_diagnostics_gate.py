from __future__ import annotations

import json
from pathlib import Path


TARGETS = (
    "eis",
    "b2b_center",
    "fabrikant_223",
    "fabrikant_44",
    "rts_tender",
    "tmk",
    "rosatom",
)
OUT = Path("output/platform_browser_diagnostics")


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise AssertionError(f"invalid PNG evidence: {path}")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def main() -> int:
    report_path = OUT / "report.json"
    if not report_path.is_file():
        raise AssertionError("browser diagnostics report.json is missing")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    failures: list[str] = []

    for target in TARGETS:
        entry = report.get(target)
        if not isinstance(entry, dict):
            failures.append(f"{target}: missing report entry")
            continue
        state = str(entry.get("diagnostic_state") or "unknown")
        result_count = entry.get("result_count")
        if state == "ok" and result_count is None:
            failures.append(f"{target}: state=ok without explicit result_count evidence")
        if state in {"unknown", "exception", "search_returned_no_evidence", "search_control_missing"}:
            failures.append(f"{target}: inconclusive diagnostic state={state}")

        screenshot = OUT / f"{target}.png"
        if not screenshot.is_file() or screenshot.stat().st_size == 0:
            failures.append(f"{target}: screenshot evidence missing")
        elif state in {"ok", "listing_available"}:
            width, height = png_dimensions(screenshot)
            if width <= 1 or height <= 1:
                failures.append(f"{target}: successful diagnostic has synthetic/1x1 screenshot")

    ci_failures = report.get("ci_failures")
    if not isinstance(ci_failures, list):
        failures.append("report: ci_failures is missing or not a list")
    elif ci_failures:
        print("Hard external/diagnostic failures remain:")
        for item in ci_failures:
            print(f"- {item}")

    if failures:
        print("Browser diagnostics artifact gate FAILED:")
        for item in failures:
            print(f"- {item}")
        return 1

    print("Browser diagnostics artifact gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
