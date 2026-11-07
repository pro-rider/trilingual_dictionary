from app.schemas.search import EntryOut, ExampleSentenceOut, SenseOut
from app.services.dataset import find_entry, load_entries
from app.services import sqlite_dataset
from app.ai.provider import generate_draft


def dictionary_search(query: str, lang: str) -> EntryOut | None:
    """Look up a word and return the canonical 3-language entry.

    Order: curated fixture (reviewed Chinese + Nepali) → merged SQLite
    dictionary (123k entries, meanings pending) → None.
    """
    entry = find_entry(query, lang)
    if entry is not None:
        return _to_entry(entry)

    wide = sqlite_dataset.find_entry(query, lang)
    if wide is not None:
        return _to_entry(wide)
    return None


def dictionary_search_with_ai(query: str, lang: str) -> EntryOut | None:
    """Dataset lookup first, then AI generation for arbitrary words.

    Returns None only when the word is not in the dataset AND AI generation is
    unavailable or failed.
    """
    entry = dictionary_search(query, lang)
    if entry is not None:
        return entry
    return _entry_from_ai(query, lang)


def _entry_from_ai(query: str, lang: str) -> EntryOut | None:
    draft = generate_draft(query, lang)
    if not draft:
        return None
    word_en = draft["word_en"]
    word_zh = draft["word_zh"]
    entry_id = f"ai-{word_en or query}"
    example = None
    if draft["example_en"] and draft["example_zh"] and draft["example_ne"]:
        example = ExampleSentenceOut(
            en=draft["example_en"],
            zh=draft["example_zh"],
            ne=draft["example_ne"],
            source="ai",
            review_status="ai_generated",
        )
    sense = SenseOut(
        sense_id=f"{entry_id}-1",
        word_en=word_en,
        word_zh=word_zh,
        pinyin=draft["pinyin"],
        ipa_en="",
        part_of_speech=draft["part_of_speech"],
        meaning_en=draft["meaning_en"],
        meaning_zh=draft["meaning_zh"],
        meaning_ne=draft["meaning_ne"],
        meaning_ne_status="ai_generated",
        examples=[example] if example else [],
    )
    return EntryOut(entry_id=entry_id, word_en=word_en, word_zh=word_zh,
                    senses=[sense])


def popular_words(limit: int = 6) -> list[str]:
    return [e["word_en"] for e in load_entries()[:limit]]


def suggest(query: str, lang: str, limit: int = 6) -> list[str]:
    q = query.strip().lower()
    if not q:
        return []
    out: list[str] = []
    for e in load_entries():
        word = e.get("word_en", "").lower() if lang == "en" else e.get(
            "word_zh", ""
        )
        if word.startswith(q) and word not in out:
            out.append(word)
        if len(out) >= limit:
            break

    # Top up from the merged dictionary so autocomplete is not capped at 6 words.
    if len(out) < limit:
        for word in sqlite_dataset.suggest(query, lang, limit - len(out)):
            if word and word not in out:
                out.append(word)
            if len(out) >= limit:
                break
    return out


def _to_entry(raw: dict) -> EntryOut:
    senses = [
        SenseOut(
            sense_id=s.get("sense_id", ""),
            word_en=s.get("word_en", ""),
            word_zh=s.get("word_zh", ""),
            pinyin=s.get("pinyin", ""),
            ipa_en=s.get("ipa_en", ""),
            part_of_speech=s.get("part_of_speech", ""),
            meaning_en=s.get("meaning_en", ""),
            meaning_zh=s.get("meaning_zh", ""),
            meaning_ne=s.get("meaning_ne", ""),
            meaning_ne_status=s.get("meaning_ne_status", "published"),
            examples=[
                ExampleSentenceOut(
                    en=x.get("en", ""),
                    zh=x.get("zh", ""),
                    ne=x.get("ne", ""),
                    source=x.get("source", "reviewed"),
                    review_status=x.get("review_status", "approved"),
                )
                for x in s.get("examples", [])
            ],
        )
        for s in raw.get("senses", [])
    ]
    return EntryOut(
        entry_id=raw.get("entry_id", ""),
        word_en=raw.get("word_en", ""),
        word_zh=raw.get("word_zh", ""),
        senses=senses,
    )
