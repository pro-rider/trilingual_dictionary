"""Mechanical validation rules — Devanagari only, no echo of the source."""

from __future__ import annotations

from translation_agent.domain.models import SenseRef
from translation_agent.validation.validator import validate_candidate


SENSE = SenseRef(
    sense_key="fixture:1001",
    entry_id=1001,
    simplified="水",
    pinyin="shui3",
    gloss_en="water",
)


def test_clean_devanagari_passes():
    result = validate_candidate("पानी", SENSE)
    assert result.ok
    assert result.code == "ok"


def test_latin_letters_are_rejected():
    result = validate_candidate("पानी water", SENSE)
    assert not result.ok
    assert result.code == "latin_in_output"


def test_cyrillic_is_rejected():
    result = validate_candidate("पानी пурсnu", SENSE)
    assert not result.ok
    assert result.code == "cyrillic_in_output"


def test_mixed_latin_inside_word_is_rejected():
    # The real defect class: Latin letters spliced into a Devanagari token.
    result = validate_candidate("बatti", SENSE)
    assert not result.ok
    assert result.code == "latin_in_output"


def test_empty_and_whitespace_are_rejected():
    assert validate_candidate("", SENSE).code == "empty"
    assert validate_candidate("   ", SENSE).code == "empty"


def test_too_long_is_rejected():
    result = validate_candidate("पानी " * 60, SENSE)
    assert not result.ok
    assert result.code == "too_long"


def test_punctuation_and_danda_are_allowed():
    for text in ("पानी।", "पानी, किताब!", "पानी (किताब)"):
        assert validate_candidate(text, SENSE).ok


def test_echo_of_english_gloss_is_rejected():
    result = validate_candidate("water", SENSE)
    assert not result.ok
    assert result.code in {"latin_in_output", "echo_source"}


def test_no_devanagari_is_rejected():
    result = validate_candidate("369", SENSE)
    assert not result.ok
    assert result.code == "no_devanagari"


def test_validation_never_returns_approval():
    # A passing mechanical check is not an approval: the API has no such field.
    result = validate_candidate("पानी", SENSE)
    assert not hasattr(result, "approved")
