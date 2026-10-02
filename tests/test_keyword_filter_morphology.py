"""Morphology + query-operator tests for KeywordFilter."""

from src.filters.keyword_filter import KeywordFilter
from src.models.tender import Tender


def _tender(text: str) -> Tender:
    return Tender(
        platform="test",
        external_id="1",
        title=text,
        url="https://example.test/1",
        description=text,
    )


def test_specific_keyword_matches_common_russian_inflection():
    filt = KeywordFilter(["станок"], [], min_text_length=1)
    assert filt.matches_strict(_tender("Поставка станков для металлообработки"))


def test_specific_keyword_matches_declension():
    filt = KeywordFilter(["подшипник"], [], min_text_length=1)
    assert filt.matches_strict(_tender("Поставка подшипников для оборудования"))


def test_specific_keyword_still_rejects_unrelated_text():
    filt = KeywordFilter(["станок"], [], min_text_length=1)
    assert not filt.matches_strict(_tender("Поставка офисных кресел и столов"))


def test_stem_fallback_does_not_match_station_word():
    filt = KeywordFilter(["станок"], [], min_text_length=1)
    assert not filt.matches_strict(_tender("Строительство станции и монтаж оборудования"))


def test_comma_or_logic():
    """Comma-separated keywords create an OR group within a single keyword."""
    filt = KeywordFilter(["станок, подшипник"], [], min_text_length=1)
    assert filt.matches_strict(_tender("Поставка станков"))
    assert filt.matches_strict(_tender("Поставка подшипников"))
    assert not filt.matches_strict(_tender("Поставка офисных кресел"))


def test_quoted_phrase_match():
    """Double-quoted terms match as exact phrases (all words must appear)."""
    filt = KeywordFilter(['"станок для"'], [], min_text_length=1)
    assert filt.matches_strict(_tender("Поставка станок для металлообработки"))
    assert not filt.matches_strict(_tender("Поставка станков"))


def test_quoted_phrase_with_comma_or():
    """Quotes + comma combine phrase and word OR."""
    filt = KeywordFilter(['"строительство поставки", станок'], [], min_text_length=1)
    assert filt.matches_strict(_tender("Документ о строительство поставки"))
    assert filt.matches_strict(_tender("Поставка станков"))
    assert not filt.matches_strict(_tender("Поставка офисных кресел"))


def test_wildcard_matches_prefix():
    """Asterisk creates a wildcard prefix match."""
    filt = KeywordFilter(["подшипн*"], [], min_text_length=1)
    assert filt.matches_strict(_tender("Поставка подшипников"))
    assert not filt.matches_strict(_tender("Поставка офисных кресел"))


def test_wildcard_matches_direct_prefix():
    """Wildcard matches words starting with the stem."""
    filt = KeywordFilter(["стан*"], [], min_text_length=1)
    assert filt.matches_strict(_tender("Поставка станков"))
    assert not filt.matches_strict(_tender("Поставка серверов"))


def test_keyword_list_or_logic():
    """Multiple keywords in the list are OR'd: any keyword matching passes."""
    filt = KeywordFilter(["станок", "подшипник"], [], min_text_length=1)
    assert filt.matches_strict(_tender("Поставка станков"))
    assert filt.matches_strict(_tender("Поставка подшипников"))


def test_empty_query_after_parsing_skipped():
    """A keyword that reduces to nothing should not crash the filter."""
    filt = KeywordFilter(["***"], [], min_text_length=1)
    assert not filt.matches_strict(_tender("Поставка подшипников"))


def test_operator_parsing_does_not_break_excludes():
    """Exclusions still work normally alongside operator parsing."""
    filt = KeywordFilter(["станок, подшипник"], ["ремонт"], min_text_length=1)
    assert not filt.matches_strict(_tender("Поставка ремонт станков"))
    assert filt.matches_strict(_tender("Поставка станков для завода"))


def test_proximity_operator_matches_words_within_distance():
    """(слово1 слово2)~N — все слова группы в пределах N слов друг от друга."""
    filt = KeywordFilter(["(поставка подшипников)~3"], [], min_text_length=1)
    assert filt.matches_strict(_tender("Поставка шариковых подшипников для насосов"))
    assert not filt.matches_strict(
        _tender("Поставка насосов и отдельно подшипников по отдельному лоту всей документации")
    )


def test_proximity_operator_applies_morphology():
    filt = KeywordFilter(["(подшипник станок)~3"], [], min_text_length=1)
    assert filt.matches_strict(_tender("Поставка подшипников и станков со склада"))


def test_proximity_operator_requires_all_words():
    filt = KeywordFilter(["(подшипник станок)~3"], [], min_text_length=1)
    assert not filt.matches_strict(_tender("Поставка подшипников всех типов и размеров"))


def test_proximity_operator_combines_with_comma_or():
    filt = KeywordFilter(['"точное совпадение", (подшипник станок)~3'], [], min_text_length=1)
    assert filt.matches_strict(_tender("Поставка подшипников и станков"))
    assert filt.matches_strict(_tender("Тут написано точное совпадение документа"))
    assert not filt.matches_strict(_tender("Поставка канцелярской продукции"))


def test_proximity_distance_limits_match_window():
    filt = KeywordFilter(["(поставка подшипников)~1"], [], min_text_length=1)
    assert filt.matches_strict(_tender("Поставка подшипников разных типов"))
    assert not filt.matches_strict(_tender("Поставка шариковых подшипников разных типов"))
