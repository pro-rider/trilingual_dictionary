"""AI fallback contract: unknown word → AI entry, flagged unverified, cached once."""

from app.core.config import settings
from app.services import ai_cache, sqlite_dataset, search


def _stub_draft(word: str, lang: str) -> dict[str, str]:
    return {
        "word_en": word,
        "word_zh": "测试",
        "pinyin": "cèshì",
        "part_of_speech": "noun",
        "meaning_en": "a stubbed gloss",
        "meaning_zh": "一个占位释义",
        "meaning_ne": "एक नमुना अर्थ",
        "example_en": "This is a stub.",
        "example_zh": "这是一个占位。",
        "example_ne": "यो एक नमुना हो।",
    }


def test_unknown_word_returns_ai_entry_and_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "dictionary_db_path", str(tmp_path / "d.sqlite"))
    sqlite_dataset.reset_cache()
    monkeypatch.setattr(search, "generate_draft", _stub_draft)

    first = search.dictionary_search_with_ai("flibbertigibbet", "en")
    assert first is not None
    assert first.source == "ai"
    assert first.unverified is True
    assert first.cached is False
    assert first.senses[0].meaning_ne == "एक नमुना अर्थ"
    assert first.senses[0].meaning_ne_status == "ai_generated"

    second = search.dictionary_search_with_ai("flibbertigibbet", "en")
    assert second is not None
    assert second.cached is True
    assert second.senses[0].meaning_ne == "एक नमुना अर्थ"


def test_ai_cache_survives_provider_failure(monkeypatch, tmp_path):
    """A cached answer must still be served when the provider is down."""
    monkeypatch.setattr(settings, "dictionary_db_path", str(tmp_path / "d.sqlite"))
    sqlite_dataset.reset_cache()
    monkeypatch.setattr(search, "generate_draft", _stub_draft)
    search.dictionary_search_with_ai("serendipity-ish", "en")

    monkeypatch.setattr(search, "generate_draft", lambda q, l: None)
    still = search.dictionary_search_with_ai("serendipity-ish", "en")
    assert still is not None and still.cached is True


def test_known_word_keeps_dictionary_source(monkeypatch):
    entry = search.dictionary_search_with_ai("light", "en")
    assert entry is not None
    assert entry.source == "dictionary"
    assert entry.unverified is False


def test_ai_cache_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "dictionary_db_path", str(tmp_path / "s.sqlite"))
    assert ai_cache.put("x", "en", {"meaning_en": "x"}) is True
    ai_cache.get("x", "en")
    assert ai_cache.stats()["rows"] == 1
