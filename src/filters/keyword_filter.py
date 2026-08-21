"""Фильтрация тендеров по ключевым словам из конфигурации."""

from __future__ import annotations

import logging
import re

from src.models.tender import Tender

logger = logging.getLogger(__name__)


class KeywordFilter:
    """Контекстный фильтр включений и исключений из keywords.yaml."""

    GENERIC_INCLUDE_PATTERNS = (
        "поставка оборудования",
        "поставка комплектующих",
        "поставка запасных частей",
        "запасные части",
        "комплектующие",
        "техническое обслуживание",
    )

    GENERIC_CONTEXT_PATTERNS = (
        "насос",
        "насосы",
        "насосного",
        "насосная",
        "компрессор",
        "компрессоры",
        "компрессорного",
        "бульдозер",
        "бульдозеры",
        "автогрейдер",
        "автогрейдера",
        "камаз",
        "маз",
        "howo",
        "трактор",
        "тракторы",
        "сельскохозяйственной техники",
        "сельскохозяйственная техника",
        "автотранспорт",
        "автотранспортных средств",
        "транспортных средств",
        "транспортной техники",
        "дорожных машин",
        "дорожные машины",
        "швейных машин",
        "швейные машины",
        "вычислительных машин",
        "принтер",
        "принтеров",
        "мфу",
        "станок",
        "станки",
        "станочного",
        "подшипник",
        "подшипники",
        "муфта",
        "муфты",
        "полумуфта",
        "полумуфты",
        "электрооборудование",
        "электротехническое оборудование",
        "оборудование связи",
        "сервер",
        "серверы",
        "серверного",
        "компьютер",
        "компьютеры",
        "компьютерного",
        "оргтехника",
        "медицинское оборудование",
        "пожарной техники",
        "пожарная техника",
        "видеонаблюдение",
        "пожарная сигнализация",
        "система пожарной сигнализации",
        "системы пожарной сигнализации",
        "системы видеонаблюдения",
        "система видеонаблюдения",
        "оборудование для дск",
        "дск",
    )

    SECONDARY_MARKERS = (
        "ввод в эксплуатацию",
        "ввод в действие",
        "обучение правилам эксплуатации",
        "обучение эксплуатации",
        "обучение специалистов",
        "инструктаж специалистов",
        "монтаж",
        "пусконаладочные работы",
        "пуско-наладочные работы",
        "наладка",
        "шеф-монтаж",
    )

    SECONDARY_PREFIXES = (
        "в том числе",
        "а также",
        "включая",
        "включительно",
    )

    def __init__(
        self,
        include: list[str],
        exclude: list[str],
        min_text_length: int = 10,
    ) -> None:
        self.include = [
            k.strip()
            for k in include
            if k and k.strip()
        ]

        self.exclude = [
            k.strip()
            for k in exclude
            if k and k.strip()
        ]

        self.min_text_length = min_text_length

        self.generic_include = tuple(
            pattern
            for pattern in self.include
            if self._is_generic_pattern(pattern)
        )

        self.specific_include = tuple(
            pattern
            for pattern in self.include
            if not self._is_generic_pattern(pattern)
        )

    @classmethod
    def _is_generic_pattern(cls, pattern: str) -> bool:
        """Определить, является ли include-ключ слишком общим."""

        normalized = cls._normalize(pattern)

        return normalized in {
            cls._normalize(item)
            for item in cls.GENERIC_INCLUDE_PATTERNS
        }

    def matches(self, tender: Tender) -> bool:
        """
        Проверить тендер на соответствие ключевым словам.

        Для ЕИС используется основной предмет закупки.
        Общие include-ключи требуют предметного контекста.
        """

        full_text = tender.full_text or ""

        if len(full_text) < self.min_text_length:
            logger.debug(
                "Пропуск %s: слишком короткий текст",
                tender.unique_key,
            )
            return False

        normalized_full = self._normalize(full_text)

        # ----------------------------------------------------------
        # 1. ИСКЛЮЧЕНИЯ
        # ----------------------------------------------------------

        for pattern in self.exclude:
            if self._contains(normalized_full, pattern):
                logger.debug(
                    "Пропуск %s: найдено исключение «%s»",
                    tender.unique_key,
                    pattern,
                )
                return False

        # ----------------------------------------------------------
        # 2. INCLUDE НЕ ЗАДАН
        # ----------------------------------------------------------

        if not self.include:
            return True

        # ----------------------------------------------------------
        # 3. ЕИС
        # ----------------------------------------------------------

        if tender.platform in {
            "eis",
            "eis_zakupki",
        }:
            title = (tender.title or "").strip()

            if not title:
                logger.debug(
                    "Пропуск %s: отсутствует название",
                    tender.unique_key,
                )
                return False

            main_subject = self._extract_main_subject(title)
            normalized_subject = self._normalize(main_subject)

            logger.debug(
                "ЕИС: основной предмет %s: %s",
                tender.external_id,
                main_subject[:500],
            )

            # ------------------------------------------------------
            # 3.1. Сначала конкретные ключи.
            # ------------------------------------------------------

            for pattern in self.specific_include:
                if self._contains(
                    normalized_subject,
                    pattern,
                ):
                    logger.debug(
                        "MATCH %s: конкретный include-ключ "
                        "«%s» найден в основном предмете: %s",
                        tender.unique_key,
                        pattern,
                        main_subject[:300],
                    )
                    return True

            # ------------------------------------------------------
            # 3.2. Общие ключи — только с предметным контекстом.
            # ------------------------------------------------------

            matched_generic = []

            for pattern in self.generic_include:
                if self._contains(
                    normalized_subject,
                    pattern,
                ):
                    matched_generic.append(pattern)

            if matched_generic:
                context = self._find_generic_context(
                    normalized_subject,
                    matched_generic,
                )

                if context:
                    logger.debug(
                        "MATCH %s: общий include-ключ %s "
                        "имеет предметный контекст %s",
                        tender.unique_key,
                        matched_generic,
                        context,
                    )
                    return True

                logger.debug(
                    "Пропуск %s: найдены только общие include-ключи "
                    "без предметного контекста: %s",
                    tender.unique_key,
                    matched_generic,
                )

            return False

        # ----------------------------------------------------------
        # 4. ДРУГИЕ ПЛАТФОРМЫ
        # ----------------------------------------------------------

        title = (tender.title or "").strip()
        normalized_title = self._normalize(title)

        for pattern in self.specific_include:
            if self._contains(
                normalized_title,
                pattern,
            ):
                return True

        matched_generic = []

        for pattern in self.generic_include:
            if self._contains(
                normalized_title,
                pattern,
            ):
                matched_generic.append(pattern)

        if matched_generic:
            context = self._find_generic_context(
                normalized_title,
                matched_generic,
            )

            if context:
                return True

        description = (tender.description or "").strip()
        normalized_description = self._normalize(description)

        for pattern in self.specific_include:
            if self._contains(
                normalized_description,
                pattern,
            ):
                return True

        for pattern in self.generic_include:
            if self._contains(
                normalized_description,
                pattern,
            ):
                context = self._find_generic_context(
                    normalized_description,
                    [pattern],
                )

                if context:
                    return True

        return False

    @classmethod
    def _find_generic_context(
        cls,
        text: str,
        matched_generic: list[str] | tuple[str, ...],
    ) -> list[str]:
        """Найти предметный контекст для общего include-ключа."""

        contexts: list[str] = []

        for context_pattern in cls.GENERIC_CONTEXT_PATTERNS:
            if cls._contains(text, context_pattern):
                contexts.append(context_pattern)

        return contexts

    @classmethod
    def _extract_main_subject(cls, title: str) -> str:
        """
        Выделить основной предмет закупки.

        Не обрезаем название по первой запятой.
        Обрезаем только перед явно распознаваемыми
        сопутствующими действиями.
        """

        text = cls._normalize(title)

        if not text:
            return ""

        cut_positions: list[int] = []

        for marker in cls.SECONDARY_MARKERS:
            match = re.search(
                r"(?:(?<=,)|(?<=;)|(?<=\s))\s*"
                + re.escape(marker)
                + r"\b",
                text,
                flags=re.IGNORECASE,
            )

            if match:
                cut_positions.append(match.start())

        for marker in cls.SECONDARY_PREFIXES:
            match = re.search(
                r"(?:(?<=,)|(?<=;)|(?<=\s))\s*"
                + re.escape(marker)
                + r"\b",
                text,
                flags=re.IGNORECASE,
            )

            if match:
                cut_positions.append(match.start())

        if not cut_positions:
            return text

        cut_position = min(cut_positions)

        main_subject = text[:cut_position].strip(" ,;:-")

        if len(main_subject) < 5:
            return text

        return main_subject

    @staticmethod
    def _normalize(text: str) -> str:
        """Нормализовать текст перед поиском."""

        text = str(text or "").lower()
        text = text.replace("\u00a0", " ")
        text = text.replace("ё", "е")
        text = re.sub(r"\s+", " ", text)

        return text.strip()

    @staticmethod
    def _contains(text: str, pattern: str) -> bool:
        """Проверить наличие ключевой фразы."""

        pattern_lower = KeywordFilter._normalize(pattern)

        if not pattern_lower:
            return False

        if len(pattern_lower) <= 3:
            return pattern_lower in text

        return bool(
            re.search(
                re.escape(pattern_lower),
                text,
            )
        )
