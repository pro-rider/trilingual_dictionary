"""The shared gloss normalizer: one definition of "where the definition starts".

These tests exist because the same rule is implemented twice — in
`app/services/gloss.py` and in `lib/data/local/offline_dictionary.dart`. The
bug they replace (`gloss.split("(")[0]`) was duplicated too, and the two copies
drifted. The Dart fixture in `test/gloss_normalizer_parity_test.dart` must
produce identical output for `PARITY_FIXTURES`; change one, change the other.
"""

from __future__ import annotations

import pytest

from app.services.gloss import extract_tags, normalize_gloss, segments, strip_tags
from app.services.sqlite_dataset import _gloss_score

PARITY_FIXTURES = [
    ("(computing) database", "database"),
    ("(lit. and fig.) to pollute; to contaminate", "to pollute; to contaminate"),
    ("(bird species of China) Nepal fulvetta", "Nepal fulvetta"),
    ("front (of a building)", "front"),
    ("a (b (c)) d", "a d"),
    ("（口语）你好", "你好"),
    ("[slang] money", "money"),
    ("(idiom) 三心二意", "三心二意"),
    ("salary", "salary"),
    ("", ""),
    ("()", ""),
    ("((nested)) (twice)", ""),
    ("  spaced   out  ", "spaced out"),
]


@pytest.mark.parametrize("raw,expected", PARITY_FIXTURES)
def test_normalize_gloss(raw, expected):
    assert normalize_gloss(raw) == expected.lower()


@pytest.mark.parametrize("raw,expected", PARITY_FIXTURES)
def test_strip_tags_keeps_case(raw, expected):
    """strip_tags preserves the original case (normalize_gloss lowercases)."""
    assert strip_tags(raw) == expected


def test_segments_split_definition_only():
    assert segments("(computing) database; record set") == ["database", "record set"]


def test_segments_handle_cjk_enumeration_comma():
    assert segments("(math.) 甲、乙") == ["甲", "乙"]


def test_tags_are_extracted_not_lost():
    assert extract_tags("(computing) database") == ["computing"]
    assert strip_tags("(computing) database") == "database"


# --- the scoring consequence -----------------------------------------------------


def test_tagged_definition_now_matches_exactly():
    """The 9.03% class: a domain tag used to zero the score."""
    assert _gloss_score("(computing) database", ["database"]) == 100


def test_tagged_definition_still_matches_after_strip():
    assert _gloss_score("(lit. and fig.) to pollute", ["pollute"]) >= 40


def test_compound_loses_to_exact_gloss():
    exact = _gloss_score("(computing) database", ["database"])
    compound = _gloss_score("database software", ["database"])
    assert exact == 100
    assert compound < exact


def test_trailing_tag_still_matches():
    assert _gloss_score("front (of a building)", ["front"]) == 100


def test_a_word_inside_a_tag_never_answers():
    """'order' must not be answered by '(in order to) ...'."""
    assert _gloss_score("(in order to) so as to", ["order"]) < 40


def test_documented_behaviour_change_for_bracket_first_glosses():
    """Honest note: stripping admits a hit where truncation gave 0.

    For "(bird species of China) Nepal fulvetta", "Nepal" is now the start of the
    definition part (score 60) instead of an empty definition (score 0). A real
    尼泊尔 ("Nepal") still scores 100 and wins, so a weak 60 only answers when
    nothing better exists. Pinned here so the change is visible, not accidental.
    """
    assert _gloss_score("(bird species of China) Nepal fulvetta", ["nepal"]) == 60


def test_empty_and_garbage_inputs():
    assert _gloss_score("", ["anything"]) == 0
    assert _gloss_score("()", ["anything"]) == 0
    assert _gloss_score("((()))", ["anything"]) == 0


# --- a leading tag that disqualifies the head -----------------------------------


def test_bound_form_head_never_answers_a_standalone_query():
    """中 = "(bound form) China; Chinese" must not answer "China" — 中国 does."""
    assert _gloss_score("(bound form) China; Chinese", ["china"]) == 0


def test_abbreviation_head_is_demoted_out():
    assert _gloss_score("(abbr. for 中国) CN", ["cn"]) == 0


def test_domain_tags_are_not_disqualifiers():
    for gloss, q in [
        ("(computing) database", "database"),
        ("(literary) to gaze", "gaze"),
        ("(slang) money", "money"),
        ("(dialect) OK", "ok"),
        ("(fig.) to rise", "rise"),
    ]:
        assert _gloss_score(gloss, [q]) == 100, gloss
