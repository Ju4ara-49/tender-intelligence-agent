"""Фильтрация тендеров по ключевым словам из конфигурации."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.models.tender import Tender

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Term:
    """A single matchable term parsed from a keyword query string."""

    text: str
    is_phrase: bool = False
    is_wildcard: bool = False
    # ``(слово1 слово2)~N``: все слова в пределах N слов друг от друга.
    proximity: int = 0
    words: tuple[str, ...] = ()


@dataclass(frozen=True)
class _QueryTree:
    """OR-group of terms parsed from a single keyword string.

    A keyword such as ``подшипники, шестёрки`` splits into two terms that
    match independently (OR). A keyword such as ``"точное совпадение"``
    becomes a single phrase term that must match verbatim.
    """

    terms: tuple[_Term, ...] = ()


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

    # Conservative endings used only after an unambiguous noun stem.
    # A short stem such as "стан" is therefore not treated as a substring:
    # "станция" has the suffix "ция", which is not in this allow-list.
    RUSSIAN_NOUN_SUFFIXES = {
        "а", "я", "ы", "и", "е", "о", "у", "ю", "ь",
        "ов", "ев", "ей", "ам", "ям", "ом", "ем", "ах", "ях",
        "ами", "ями", "ою", "ею", "ой", "ью",
        # Pattern "подшипник" -> stem "подшипн".
        "ик", "ика", "ику", "иком", "ике", "ики", "иков", "иками", "иках",
        # Pattern "станок" -> stem "стан".
        "к", "ка", "ку", "ком", "ке", "ки", "ков", "ками", "ках",
    }

    def __init__(self, include: list[str], exclude: list[str], min_text_length: int = 10, search_documents: bool = True) -> None:
        self.include = [k.strip() for k in include if k and k.strip()]
        self.exclude = [k.strip() for k in exclude if k and k.strip()]
        self.min_text_length = min_text_length
        self.search_documents = search_documents
        self.generic_include = tuple(k for k in self.include if self._is_generic_pattern(k))
        self.specific_include = tuple(k for k in self.include if not self._is_generic_pattern(k))
        self._query_trees = [self._parse_query(k) for k in self.specific_include]

    @classmethod
    def _is_generic_pattern(cls, pattern: str) -> bool:
        normalized = cls._normalize(pattern)
        return normalized in {cls._normalize(item) for item in cls.GENERIC_INCLUDE_PATTERNS}

    @classmethod
    def _parse_query(cls, raw: str) -> _QueryTree:
        """Parse a single keyword string into an OR-group of matchable terms.

        Supports query operators:
        - Comma → OR split: ``"подшипники, шестёрки"`` matches either term.
        - Double quotes → exact phrase: ``'"бетонный шнек"'`` matches verbatim.
        - Trailing asterisk → wildcard prefix: ``"подшипн*"`` matches any
          word starting with ``подшипн`` (morphology applies).
        - ``(слово1 слово2)~N`` → proximity: все слова группы обязаны
          встретиться в пределах N слов друг от друга (морфология применяется).
        """
        normalized = cls._normalize(raw)
        if not normalized:
            return _QueryTree(terms=())
        terms: list[_Term] = []
        for part in re.split(r"\s*,\s*", normalized):
            if not part:
                continue
            proximity_match = re.fullmatch(r"\((.+)\)~(\d{1,3})", part)
            if proximity_match:
                words = tuple(
                    word
                    for word in dict.fromkeys(proximity_match.group(1).split())
                    if word
                )
                if words:
                    terms.append(
                        _Term(
                            text=" ".join(words),
                            proximity=int(proximity_match.group(2)),
                            words=words,
                        )
                    )
            elif part.startswith('"') and part.endswith('"') and len(part) >= 2:
                inner = part[1:-1].strip()
                if inner:
                    terms.append(_Term(text=cls._normalize(inner), is_phrase=True))
            elif "*" in part:
                for star_part in re.split(r"\s+", part):
                    star_part = star_part.strip()
                    if not star_part or "*" not in star_part:
                        continue
                    stem = star_part.replace("*", "").strip()
                    if stem:
                        terms.append(_Term(text=cls._normalize(stem), is_wildcard=True))
            else:
                terms.append(_Term(text=cls._normalize(part)))
        return _QueryTree(terms=tuple(terms))

    def _term_matches(self, text: str, term: _Term) -> bool:
        if not term.text:
            return False
        if term.proximity:
            return self._contains_proximity(text, term.words, term.proximity)
        if term.is_phrase:
            return self._contains(text, term.text)
        if term.is_wildcard:
            return self._contains_wildcard(text, term.text)
        return self._contains(text, term.text)

    @classmethod
    def _contains_proximity(cls, text: str, words: tuple[str, ...], distance: int) -> bool:
        """``(слово1 слово2)~N``: все слова в пределах N слов друг от друга.

        Расстояние считается по позициям слов в нормализованном тексте:
        существует набор вхождений (по одному на каждое слово группы), у
        которого ``max(позиции) - min(позиции) <= N``. Морфология словоформ
        применяется так же, как в обычном включающем фильтре.
        """
        if not words or distance < 0:
            return False
        tokens = re.findall(r"[\w-]+", text, re.UNICODE)
        if not tokens:
            return False
        positions: list[list[int]] = []
        for word in words:
            hits = [
                index
                for index, token in enumerate(tokens)
                if cls._token_matches_word(token, word)
            ]
            if not hits:
                return False
            positions.append(hits)
        # Минимальное окно, покрывающее по одному вхождению каждого слова
        # (классический проход k отсортированных списков позиций).
        pointers = [0] * len(positions)
        current = [group[0] for group in positions]
        while True:
            if max(current) - min(current) <= distance:
                return True
            min_group = current.index(min(current))
            pointers[min_group] += 1
            if pointers[min_group] >= len(positions[min_group]):
                return False
            current[min_group] = positions[min_group][pointers[min_group]]

    @classmethod
    def _token_matches_word(cls, token: str, word: str) -> bool:
        """Сравнение одного токена текста со словом запроса (с морфологией)."""
        if not token or not word:
            return False
        if token == word:
            return True
        if len(word) >= 6:
            stem = word[:-2]
            if (
                len(stem) >= 4
                and token.startswith(stem)
                and token[len(stem):] in cls.RUSSIAN_NOUN_SUFFIXES
            ):
                return True
        return False

    def _has_direct_include_match(self, text: str) -> bool:
        """Allow a short title that itself exactly matches an include keyword.

        The minimum-text guard is meant to reject empty/skeleton discovery rows,
        not legitimate procedures whose entire title is a short keyword such as
        ``Подшипник``.  This check does not bypass exclusions.
        """
        normalized = self._normalize(text)
        return any(self._contains(normalized, pattern) for pattern in self.include)

    def _tender_text(self, tender: Tender) -> str:
        """Return full_text or search_text depending on search_documents flag."""
        if not self.search_documents:
            return tender.search_text or ""
        return tender.full_text or ""

    def matches_soft(self, tender: Tender) -> bool:
        """Дешёвый pre-filter: исключения + минимальный объём текста."""
        full_text = self._tender_text(tender)
        normalized = self._normalize(full_text)
        for pattern in self.exclude:
            if self._contains(normalized, pattern):
                logger.debug("Пропуск %s: найдено исключение «%s»", tender.unique_key, pattern)
                return False
        if len(full_text) < self.min_text_length and not self._has_direct_include_match(full_text):
            logger.debug("Пропуск %s: слишком короткий текст", tender.unique_key)
            return False
        return True

    @staticmethod
    def _b2b_details_are_complete(tender: Tender) -> bool:
        """Require successful detail loading before strict B2B-Center matching.

        B2B-Center discovery intentionally returns lightweight rows. Those rows
        are not safe for final filtering because title-only data can produce false
        positives and missing commercial fields can bypass downstream criteria.
        The detail collector marks a successful load with ``details_loaded=True``.
        """
        if tender.platform != "b2b_center":
            return True

        raw = tender.raw_data if isinstance(tender.raw_data, dict) else {}
        if raw.get("details_loaded") is not True:
            return False
        if not str(tender.customer or "").strip():
            return False
        if tender.price is None:
            return False
        if tender.deadline is None and tender.end_date is None:
            return False
        return True

    def matches_strict(self, tender: Tender) -> bool:
        """Финальный INCLUDE-фильтр по полному тексту тендера."""
        if not self.matches_soft(tender):
            return False
        if not self._b2b_details_are_complete(tender):
            logger.debug("Пропуск %s: B2B-Center details incomplete", tender.unique_key)
            return False
        if not self.include:
            return True

        text = self._normalize(self._tender_text(tender))
        for tree in self._query_trees:
            if any(self._term_matches(text, term) for term in tree.terms):
                return True

        matched_generic = [p for p in self.generic_include if self._contains(text, p)]
        if matched_generic:
            return bool(self._find_generic_context(text, matched_generic))
        return False

    def matches(self, tender: Tender) -> bool:
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

    @classmethod
    def _contains(cls, text: str, pattern: str) -> bool:
        pattern_lower = cls._normalize(pattern)
        if not pattern_lower:
            return False
        words = re.findall(r"[\w-]+", pattern_lower, re.UNICODE)
        if not words:
            return False
        if len(words) > 1:
            return all(cls._contains_word(text, word) for word in words)
        return cls._contains_word(text, words[0])

    @classmethod
    def _contains_word(cls, text: str, word: str) -> bool:
        if re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text, re.UNICODE):
            return True
        if len(word) < 6:
            return False

        # Conservative two-character stem fallback. This deliberately requires
        # a known noun ending, so "стан" cannot match "станция" while
        # "станок" matches "станки"/"станков" and "подшипник" matches
        # "подшипники".
        stem = word[:-2]
        if len(stem) < 4:
            return False
        pattern = rf"(?<![\w-]){re.escape(stem)}(?P<suffix>[\w-]*)(?![\w-])"
        for match in re.finditer(pattern, text, re.UNICODE):
            suffix = match.group("suffix")
            if suffix in cls.RUSSIAN_NOUN_SUFFIXES:
                return True
        return False

    @classmethod
    def _contains_wildcard(cls, text: str, stem: str) -> bool:
        """Wildcard prefix match: ``подшипн*`` matches ``подшипники`` etc.

        Falls through to morphology-based stem matching for inflected forms.
        """
        if not stem or len(stem) < 2:
            return False
        escaped = re.escape(stem)
        if re.search(rf"(?<![\w-]){escaped}[\w-]*", text, re.UNICODE):
            return True
        if len(stem) >= 6:
            short_stem = stem[:-2]
            if len(short_stem) >= 4:
                pattern = rf"(?<![\w-]){re.escape(short_stem)}(?P<suffix>[\w-]*)(?![\w-])"
                for match in re.finditer(pattern, text, re.UNICODE):
                    if match.group("suffix") in cls.RUSSIAN_NOUN_SUFFIXES:
                        return True
        return False
