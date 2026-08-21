"""Базовый интерфейс сборщиков тендеров."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.models.tender import Tender


class BaseCollector(ABC):
    """
    Базовый класс для всех площадок.

    Чтобы добавить новую площадку:
    1. Создайте файл в collectors/ (например, sberbank_ast.py)
    2. Унаследуйте BaseCollector
    3. Зарегистрируйте класс в collectors/registry.py
    """

    platform: str = "unknown"

    @abstractmethod
    def search(
        self,
        keywords: list[str],
        since: datetime | None = None,
    ) -> list[Tender]:
        """Найти тендеры по ключевым словам."""

    @abstractmethod
    def get_details(self, external_id: str) -> Tender | None:
        """Получить детали одного тендера."""

    def is_enabled(self, config: dict) -> bool:
        """Проверить, включён ли сборщик в config.yaml."""
        collectors = config.get("collectors", {})
        platform_config = collectors.get(self.platform, {})
        return bool(platform_config.get("enabled", False))

    def get_platform_config(self, config: dict) -> dict:
        """Получить секцию настроек для этой площадки."""
        return dict(config.get("collectors", {}).get(self.platform, {}))
