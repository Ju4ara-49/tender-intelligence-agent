"""Загрузка настроек из YAML и .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

DEFAULT_CONFIG = CONFIG_DIR / "config.yaml"
EXAMPLE_CONFIG = CONFIG_DIR / "config.example.yaml"
DEFAULT_KEYWORDS = CONFIG_DIR / "keywords.yaml"
EXAMPLE_KEYWORDS = CONFIG_DIR / "keywords.example.yaml"


@dataclass
class AppSettings:
    """Все настройки приложения."""

    config: dict[str, Any]
    keywords: dict[str, Any]

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    ai_api_key: str = ""
    ai_api_base: str = ""
    ai_model: str = "qwen3:8b"
    ai_provider: str = "ollama"
    ollama_url: str = "http://localhost:11434"

    log_level: str = "INFO"

    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)

    @property
    def database_path(self) -> Path:
        rel = self.config.get("storage", {}).get(
            "database_path",
            "data/tenders.db",
        )
        return self.project_root / rel

    @property
    def log_file(self) -> Path:
        rel = self.config.get("logging", {}).get(
            "file",
            "logs/agent.log",
        )
        return self.project_root / rel

    @property
    def include_keywords(self) -> list[str]:
        return list(self.keywords.get("include", []))

    @property
    def exclude_keywords(self) -> list[str]:
        return list(self.keywords.get("exclude", []))

    @property
    def ai_context(self) -> str:
        return str(self.keywords.get("ai_context", "")).strip()

    @property
    def min_relevance_score(self) -> int:
        return int(
            self.config.get("ai", {}).get(
                "min_relevance_score",
                70,
            )
        )

    @property
    def scheduler_interval_minutes(self) -> int:
        return int(
            self.config.get("scheduler", {}).get(
                "interval_minutes",
                60,
            )
        )

    @property
    def run_on_start(self) -> bool:
        return bool(
            self.config.get("scheduler", {}).get(
                "run_on_start",
                True,
            )
        )

    @property
    def telegram_dry_run(self) -> bool:
        return bool(
            self.config.get("notifications", {})
            .get("telegram", {})
            .get("dry_run_when_no_token", True)
        )

    @property
    def ai_use_stub(self) -> bool:
        return bool(
            self.config.get("ai", {}).get(
                "use_stub_when_no_key",
                False,
            )
        )


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data if isinstance(data, dict) else {}


def _resolve_config_path() -> Path:
    if DEFAULT_CONFIG.exists():
        return DEFAULT_CONFIG

    if EXAMPLE_CONFIG.exists():
        return EXAMPLE_CONFIG

    raise FileNotFoundError(
        f"Не найден config.yaml или config.example.yaml в {CONFIG_DIR}"
    )


def _resolve_keywords_path() -> Path:
    if DEFAULT_KEYWORDS.exists():
        return DEFAULT_KEYWORDS

    if EXAMPLE_KEYWORDS.exists():
        return EXAMPLE_KEYWORDS

    raise FileNotFoundError(
        f"Не найден keywords.yaml или keywords.example.yaml в {CONFIG_DIR}"
    )


def load_settings(env_file: Path | None = None) -> AppSettings:
    """Загрузить все настройки."""

    env_path = env_file or (PROJECT_ROOT / ".env")

    if env_path.exists():
        load_dotenv(env_path)

    config = _load_yaml(_resolve_config_path())
    keywords = _load_yaml(_resolve_keywords_path())

    ai_config = config.get("ai", {})

    return AppSettings(
        config=config,
        keywords=keywords,

        telegram_bot_token=os.getenv(
            "TELEGRAM_BOT_TOKEN",
            "",
        ).strip(),

        telegram_chat_id=os.getenv(
            "TELEGRAM_CHAT_ID",
            "",
        ).strip(),

        # OpenAI больше не используется.
        ai_api_key="",

        ai_api_base="",

        ai_model=os.getenv(
            "AI_MODEL",
            ai_config.get("model", "qwen3:8b"),
        ).strip(),

        ai_provider=os.getenv(
            "AI_PROVIDER",
            ai_config.get("provider", "ollama"),
        ).strip(),

        ollama_url=os.getenv(
            "OLLAMA_URL",
            ai_config.get(
                "ollama_url",
                "http://localhost:11434",
            ),
        ).strip(),

        log_level=os.getenv(
            "LOG_LEVEL",
            "INFO",
        ).strip(),
    )