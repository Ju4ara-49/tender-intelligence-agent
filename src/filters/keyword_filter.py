"""Фильтрация тендеров по ключевым словам из конфигурации."""

from __future__ import annotations

import logging
import re

from src.models.tender import Tender

logger = logging.getLogger(__name__)


class KeywordFilter:
    """Broad discovery + strict post-filter по полному тексту тендера."""

    GENERIC_INCLUDE_PATTERNS = (
        "поставка оборудования", "поставка комплектующих", "поставка запасных частей",
        "запасные части", "комплектующие", "техническое обслуживание",
    )

    GENERIC_CONTEXT_PATTERNS = (
        "насос", "насосы", "насосного", "насосная", "компрессор", "компрессоры",
        "компрессорного", "бульдозер", "бульдозеры", "автогрейдер", "автогрейдера",
        "камаз", "маз", "howo", "трактор", "тракторы", "сельскохозяйственной техники",
        "сельскохозяйственная техника", "автотранспорт", "автотранспортных средств",
        "транспортных средств", "транспортной техники", "дорожных машин", "дорожные машины",
        "швейных машин", "швейные машины", "вычислительных машин", "принтер", "принтеров",
        "мфу", "станок", "станки", "станочного", "подшипник", "подшипники", "муфта", "муфты",
        "полумуфта", "полумуфты", "редуктор", "редукторы", "редукторный", "электрооборудование",
        "электротехническое оборудование", "оборудование связи", "сервер", "серверы", "серверного",
        "компьютер", "компьютеры", "компьютерного", "оргтехника", "медицинское оборудование",
        "пожарной техники", "пожарная техника", "видеонаблюдение", "пожарная сигнализация",
        "система пожарной сигнализации", "системы пожарной сигнализации", "системы видеонаблюдения",
        "система видеонаблюдения", "оборудование для дск", "дск",
    )

    def __init__(self, include: list[str], exclude: list[str], min_text_length: int = 10) -> None:
        self.include = [k.strip() for k in include if k and k.strip()]
        self.exclude = [k.strip() for k in exclude if k and k.strip()]
        self.min_text_length = min_text_length
        self.generic_include = tuple(k for k in self.include if self._is_generic_pattern(k))
        self.specific_include = tuple(k for k in self.include if not self._is_generic_pattern(k))

    @classmethod
    def _is_generic_pattern(cls, pattern: str) -> bool:
        normalized = cls._normalize(pattern)
        return normalized in {cls._normalize(item) for item in cls.GENERIC_INCLUDE_PATTERNS}

    def matches_soft(self, tender: Tender) -> bool:
        """Дешёвый pre-filter: исключения + минимальный объём текста.

        INCLUDE здесь намеренно НЕ применяется. Сначала нужно получить детали,
        лоты и спецификацию, иначе релевантные закупки теряются слишком рано.
        """
        full_text = tender.full_text or ""
        if len(full_text) < self.min_text_length:
            logger.debug("Пропуск %s: слишком короткий текст", tender.unique_key)
            return False
        normalized = self._normalize(full_text)
        for pattern in self.exclude:
            if self._contains(normalized, pattern):
                logger.debug("Пропуск %s: найдено исключение «%s»", tender.unique_key, pattern)
                return False
        return True

    def matches_strict(self, tender: Tender) -> bool:
        """Финальный INCLUDE-фильтр по title/description/details/lots/specification."""
        if not self.matches_soft(tender):
            return False
        if not self.include:
            return True

        text = self._normalize(tender.full_text)
        for pattern in self.specific_include:
            if self._contains(text, pattern):
                return True

        matched_generic = [p for p in self.generic_include if self._contains(text, p)]
        if matched_generic:
            return bool(self._find_generic_context(text, matched_generic))
        return False

    def matches(self, tender: Tender) -> bool:
        """Совместимость со старым API: теперь это строгая проверка."""
        return self.matches_strict(tender)

    @classmethod
    def _find_generic_context(cls, text: str, matched_generic: list[str] | tuple[str, ...]) -> list[str]:
        del matched_generic
        return [pattern for pattern in cls.GENERIC_CONTEXT_PATTERNS if cls._contains(text, pattern)]

    @staticmethod
    def _normalize(text: str) -> str:
        text = str(text or "").lower().replace("\u00a0", " ").replace("ё", "е")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _contains(text: str, pattern: str) -> bool:
        pattern_lower = KeywordFilter._normalize(pattern)
        if not pattern_lower:
            return False
        if len(pattern_lower) <= 3:
            return pattern_lower in text
        return bool(re.search(re.escape(pattern_lower), text))
