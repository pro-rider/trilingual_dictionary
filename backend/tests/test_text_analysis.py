"""Unit tests for the text-analysis engine (offline, AI stubbed out)."""

import pytest

from app.text_analysis import analyzer
from app.text_analysis.analyzer import analyze_text


@pytest.fixture(autouse=True)
def _no_ai(monkeypatch):
    """Never call the real AI in unit tests — keep them fast and deterministic."""
    monkeypatch.setattr(analyzer, "analyze_text_with_ai", lambda *a, **k: None)


def test_compound_fruit_not_split():
    """水果 resolves as one compound = fruit, NOT 水 + 果."""
    res = analyze_text("水果", "auto")
    segs = [s for s in res.segments if s.kind != "punctuation"]
    assert len(segs) == 1
    seg = segs[0]
    assert seg.surface == "水果"
    assert seg.kind in ("compound", "word")
    assert seg.word_en == "fruit"
    assert seg.meaning_ne == "फल"
    assert seg.pinyin == "shuǐguǒ"
    assert seg.source == "phrase"
    assert res.degraded is False


def test_mixed_compound_and_char():
    """水果和苹果 → 水果 + 和 + 苹果; compound entries win over single chars."""
    res = analyze_text("水果和苹果", "auto")
    surfaces = [s.surface for s in res.segments]
    assert "水果" in surfaces
    assert "苹果" in surfaces
    fruit = next(s for s in res.segments if s.surface == "水果")
    assert fruit.kind == "compound"
    assert fruit.word_en == "fruit"


def test_english_idiom_own_meaning():
    """a piece of cake → idiom with its own (figurative) meaning."""
    res = analyze_text("This task is a piece of cake.", "auto")
    idioms = [s for s in res.segments if s.kind == "idiom"]
    assert len(idioms) == 1
    seg = idioms[0]
    assert seg.surface == "a piece of cake"
    assert "easy" in seg.meaning_en.lower()
    assert "小菜" in seg.meaning_zh or "轻而易举" in seg.meaning_zh
    assert seg.source == "phrase"


def test_english_word_from_dataset():
    """water resolves from the offline dataset; unknown words degrade."""
    res = analyze_text("water flows through the valley", "auto")
    water = next(s for s in res.segments if s.surface.lower() == "water")
    assert water.source == "dataset"
    assert "liquid" in water.meaning_en.lower()
    # Unknown words without AI are marked unresolved and the result degrades.
    assert res.degraded is True
    unresolved = [s for s in res.segments if s.source == "unresolved"]
    assert any(s.surface.lower() in ("flows", "through", "the", "valley")
               for s in unresolved)


def test_chinese_word_from_dataset():
    """Single dataset Chinese word resolves without AI."""
    res = analyze_text("水", "auto")
    seg = res.segments[0]
    assert seg.surface == "水"
    assert seg.source == "dataset"
    assert seg.meaning_ne == "पानी"


def test_empty_input():
    res = analyze_text("   ", "auto")
    assert res.error != ""
    assert res.segments == []


def test_punctuation_kept_as_segments():
    res = analyze_text("Hello!", "auto")
    punct = [s for s in res.segments if s.kind == "punctuation"]
    assert any(s.surface == "!" for s in punct)


def test_chinese_sentence_segments_into_words_not_chars():
    """Real segmentation: 今天天气很好 → 今天 + 天气 + 很好, not 今+天+天+气."""
    pytest.importorskip("jieba")
    res = analyze_text("今天天气很好，我们去公园散步。", "auto")
    surfaces = [s.surface for s in res.segments if s.kind != "punctuation"]
    for word in ("今天", "天气", "公园", "散步"):
        assert word in surfaces, f"{word} should be one word, got {surfaces}"
    # No isolated single characters for the words jieba knows.
    assert "公" not in surfaces and "园" not in surfaces


def test_english_stopwords_are_not_degraded():
    """"The" is grammatical glue: shown in text, never an unresolved failure."""
    res = analyze_text("The water", "auto")
    the = next(s for s in res.segments if s.surface == "The")
    assert the.kind == "function"
    assert the.source == "stopword"
    assert res.degraded is False


def test_ai_match_is_case_insensitive(monkeypatch):
    """AI returns "the"; the segment is "The" — it must still resolve."""
    monkeypatch.setattr(
        analyzer,
        "analyze_text_with_ai",
        lambda *a, **k: {
            "words": {"bird": {"kind": "word", "word_en": "bird",
                               "meaning_en": "a flying animal",
                               "meaning_ne": "चरा"}},
            "whole": {"en": "x", "zh": "", "ne": ""},
        },
    )
    res = analyze_text("Bird flies", "auto")
    bird = next(s for s in res.segments if s.surface == "Bird")
    assert bird.source == "ai"
    assert bird.meaning_ne == "चरा"


def test_english_proverb_matched_as_idiom():
    res = analyze_text("The early bird catches the worm.", "auto")
    idioms = [s for s in res.segments if s.kind == "idiom"]
    assert len(idioms) == 1
    assert idioms[0].surface == "the early bird catches the worm"
    assert "advantage" in idioms[0].meaning_en.lower()


def test_ai_span_merge_of_adjacent_units(monkeypatch):
    """The model merges 很 + 好 → 很好; that span must be accepted, not lost."""
    pytest.importorskip("jieba")
    monkeypatch.setattr(
        analyzer,
        "analyze_text_with_ai",
        lambda *a, **k: {
            "words": {
                "天气": {"kind": "compound", "word_en": "weather",
                       "meaning_ne": "मौसम"},
                "很好": {"kind": "phrase", "word_en": "very good",
                       "meaning_ne": "बहुत राम्रो"},
            },
            "whole": {},
        },
    )
    res = analyze_text("天气很好", "auto")
    surfaces = [s.surface for s in res.segments]
    assert "很好" in surfaces
    merged = next(s for s in res.segments if s.surface == "很好")
    assert merged.meaning_ne == "बहुत राम्रो"
    assert res.degraded is False
