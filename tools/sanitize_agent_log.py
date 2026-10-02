"""Безопасная очистка секретов из существующих логов (P0 security fix).

НЕ запускается автоматически. По умолчанию — dry-run: только отчёт
(без вывода самих секретов). С флагом --apply переписывает лог,
маскируя Telegram-токены, и сохраняет резервную копию рядом.

Использование:
    python tools/sanitize_agent_log.py                # dry-run по logs/agent.log
    python tools/sanitize_agent_log.py --apply        # очистить logs/agent.log
    python tools/sanitize_agent_log.py --apply --delete-backup
                                                      # после проверки удалить .bak
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.security_redaction import redact_secrets  # noqa: E402


def load_known_tokens() -> list[str]:
    try:
        from src.settings import load_settings

        return get_known_tokens_safe(load_settings())
    except Exception:
        return []


def get_known_tokens_safe(settings) -> list[str]:
    from src.security_redaction import get_known_telegram_tokens

    return get_known_telegram_tokens(settings)


def sanitize_file(path: Path, known_tokens: list[str], apply: bool, delete_backup: bool) -> None:
    if not path.exists():
        print(f"Файл не найден: {path}")
        return
    affected = 0
    original_lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    cleaned: list[str] = []
    for line in original_lines:
        cleaned_line = redact_secrets(line, known_tokens)
        if cleaned_line != line:
            affected += 1
        cleaned.append(cleaned_line)
    status = "DRY-RUN" if not apply else "APPLIED"
    print(f"{status}: {path.name} — строк с секретами: {affected} (токен не выводится)")
    if apply and affected:
        backup = path.with_name(path.name + ".bak")
        backup.write_text("".join(original_lines), encoding="utf-8")
        path.write_text("".join(cleaned), encoding="utf-8")
        print(f"Очищено: {path.name}; резервная копия: {backup.name}")
        if delete_backup and backup.exists():
            backup.unlink()
            print(f"Резервная копия удалена: {backup.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Маскирует Telegram-токены в логах (dry-run по умолчанию)")
    parser.add_argument("--apply", action="store_true", help="переписать лог с маскированием")
    parser.add_argument("--delete-backup", action="store_true", help="удалить резервную .bak-копию после apply")
    parser.add_argument("--file", default=str(PROJECT_ROOT / "logs" / "agent.log"))
    args = parser.parse_args()
    sanitize_file(Path(args.file), load_known_tokens(), args.apply, args.delete_backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
