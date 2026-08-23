"""Create a safe, useful B2B-Center probe extract.

Removes cookies/tokens/storage and keeps request/response metadata needed for
reverse-engineering the modern B2B-Center search API.

Usage:
    python tools/sanitize_b2b_probe.py output/b2b_network_probe_YYYYMMDD_HHMMSS.txt

The sanitized file is written next to the source with *_sanitized.txt suffix.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_HEADER = re.compile(
    r"^(cookie|authorization|proxy-authorization|x-api-key|x-auth-token|x-csrf-token)$",
    re.I,
)
SENSITIVE_KEY = re.compile(
    r"(token|access[_-]?token|refresh[_-]?token|authorization|cookie|session|secret|password|passwd|csrf|xsrf|api[_-]?key)",
    re.I,
)


def safe_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
        pairs = []
        for key, value in parse_qsl(p.query, keep_blank_values=True):
            if SENSITIVE_KEY.search(key):
                value = "[REDACTED]"
            pairs.append((key, value))
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(pairs), ""))
    except Exception:
        return re.sub(r"(?i)(token|key|secret|session|auth)=[^&\s]+", r"\1=[REDACTED]", url)


def redact_jsonish(text: str) -> str:
    # Preserve useful JSON structure while removing obvious secret fields.
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        quote = match.group(2)
        return f'"{key}": {quote}[REDACTED]{quote}'

    return re.sub(
        r'"([^"\n]+)"\s*:\s*(["\'])(.*?)\2',
        lambda m: m.group(0) if not SENSITIVE_KEY.search(m.group(1)) else f'"{m.group(1)}": "[REDACTED]"',
        text,
    )


def sanitize(src: Path) -> Path:
    out = src.with_name(src.stem + "_sanitized.txt")
    lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
    result: list[str] = []
    section = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("=== "):
            section = stripped
            if section in {
                "=== LOCAL STORAGE ===",
                "=== SESSION STORAGE ===",
            }:
                result.append(section)
                result.append("[REDACTED: browser storage intentionally omitted]")
            else:
                result.append(line)
            continue

        if section in {"=== LOCAL STORAGE ===", "=== SESSION STORAGE ==="}:
            continue

        # Drop raw console noise that is not useful for API discovery if it
        # contains credential-like material.
        if any(SENSITIVE_KEY.search(k) for k in re.findall(r'"([^"\n]+)"\s*:', line)):
            line = redact_jsonish(line)

        if line.startswith("  HEADERS="):
            # Remove sensitive headers from the serialized header object.
            parts = re.split(r'("[^"]+"\s*:\s*)', line)
            rebuilt = []
            i = 0
            while i < len(parts):
                if i + 1 < len(parts) and parts[i].startswith('"') and parts[i].endswith(": "):
                    key = parts[i][1:parts[i].rfind('"')]
                    if SENSITIVE_HEADER.match(key):
                        rebuilt.extend([parts[i], '"[REDACTED]"'])
                        i += 2
                        continue
                rebuilt.append(parts[i])
                i += 1
            line = "".join(rebuilt)

        # Normalize URLs everywhere we can recognize them.
        line = re.sub(r'https?://[^\s"<>]+', lambda m: safe_url(m.group(0)), line)

        # Never keep raw response bodies for known telemetry/error endpoints.
        low = line.lower()
        if any(x in low for x in ("front-errors.b2b-center.ru", "visor.b2b-center.ru", "counter.yadro.ru")):
            continue

        result.append(line)

    out.write_text("\n".join(result) + "\n", encoding="utf-8")
    return out


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/sanitize_b2b_probe.py <probe.txt>")
        return 2
    src = Path(sys.argv[1])
    if not src.is_file():
        print(f"File not found: {src}")
        return 2
    out = sanitize(src)
    print(f"Sanitized B2B probe: {out}")
    print(f"Size: {out.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
