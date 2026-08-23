"""Compatibility/runtime registration for additional tender platforms."""
from __future__ import annotations

from src.telegram_bot import PLATFORM_NAMES
from src.telegram_settings import SUPPORTED_PLATFORMS
from src.collectors.fabrikant import FabrikantCollector
from src.collectors.registry import ALL_COLLECTORS
from src.telegram_multiuser import MultiUserTelegramBot


# UniPro окончательно выведен из проекта. Фабрикант занимает его место.
if "unipro" in SUPPORTED_PLATFORMS:
    SUPPORTED_PLATFORMS.remove("unipro")
PLATFORM_NAMES.pop("unipro", None)

_EXTRA_PLATFORMS = {
    "rosatom": "Росатом",
    "fabrikant": "Фабрикант",
}

for platform, name in _EXTRA_PLATFORMS.items():
    if platform not in SUPPORTED_PLATFORMS:
        SUPPORTED_PLATFORMS.append(platform)
    PLATFORM_NAMES[platform] = name

# Backward-compatible runtime registration. This is intentionally idempotent.
if not any(cls.platform == FabrikantCollector.platform for cls in ALL_COLLECTORS):
    ALL_COLLECTORS.append(FabrikantCollector)


# The Telegram search runs in a background thread.  CriteriaStore historically
# inferred chat_id from the call stack; make the user context explicit at the
# actual search-thread boundary so platform selection cannot silently fall back
# to the default user.
_original_run_search_for_user = MultiUserTelegramBot._run_search_for_user


def _run_search_for_user_with_explicit_context(self, chat_id, orchestrator):
    orchestrator.criteria_store.set_user_id(chat_id)
    return _original_run_search_for_user(self, chat_id, orchestrator)


MultiUserTelegramBot._run_search_for_user = _run_search_for_user_with_explicit_context
