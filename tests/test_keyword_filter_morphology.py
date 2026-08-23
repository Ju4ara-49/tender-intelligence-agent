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
