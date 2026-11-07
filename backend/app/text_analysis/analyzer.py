"""Orchestrator: segment → classify → resolve → assemble the analyze response.

Local dataset + curated phrase DB are tried first (fast, free, offline); any
unit not resolved is collected and handled in ONE batched AI call. If AI is
unavailable, those units are left marked ``unresolved`` and ``degraded=True``
so the UI degrades gracefully instead of failing.
"""

from __future__ import annotations

from functools import lru_cache

from app.ai.provider import analyze_text_with_ai
from app.schemas.search import EntryOut, SenseOut
from app.services.dataset import load_entries
from app.text_analysis.phrases import (
    chinese_word,
    cjk_idiom,
    english_idiom_tokens,
)
from app.text_analysis.schemas import (
    AnalyzeTextResponse,
    AnalyzedSegment,
    WholeTranslation,
)
from app.text_analysis.segmenter import meaningful, tokenize

# Cap on units sent to the AI in one call (protects latency + cost).
_MAX_AI_SURFACES = 60

# Grammatical words carry no dictionary meaning of their own. They stay in the
# analyzed text for readability but are never sent to the AI and never make a
# result look "degraded".
_EN_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at", "by",
    "for", "with", "from", "as", "is", "am", "are", "was", "were", "be", "been",
    "being", "do", "does", "did", "has", "have", "had", "it", "its", "this",
    "that", "these", "those", "i", "you", "he", "she", "we", "they", "me",
    "him", "her", "us", "them", "my", "your", "his", "their", "our", "not",
    "no", "so", "if", "than", "then", "there", "here", "will", "would", "can",
    "could", "should", "may", "might", "must", "very", "just", "also",
})
_CJK_STOPWORDS = frozenset({
    "的", "地", "得", "了", "着", "吗", "呢", "吧", "啊", "呀", "嘛", "哦",
})

# Segment kinds that do not represent a translatable content word.
_NON_CONTENT_KINDS = ("punctuation", "function")


def _norm(surface: str) -> str:
    """Key for matching AI output back to a segment ("The" == "the")."""
    return surface.strip().lower()


@lru_cache(maxsize=1)
def _dataset_index() -> dict[str, EntryOut]:
    """In-memory word → entry index (English-lower and Chinese surfaces)."""
    index: dict[str, EntryOut] = {}
    for e in load_entries():
        en = (e.get("word_en") or "").strip().lower()
        if en:
            index.setdefault(en, _to_entry(e))
        zh = (e.get("word_zh") or "").strip()
        if zh:
            index.setdefault(zh, _to_entry(e))
        for s in e.get("senses", []):
            zh_s = (s.get("word_zh") or "").strip()
            if zh_s:
                index.setdefault(zh_s, _to_entry(e))
    return index


def _to_entry(raw: dict) -> EntryOut:
    senses = [
        SenseOut(
            sense_id=s.get("sense_id", ""),
            word_en=s.get("word_en", ""),
            word_zh=s.get("word_zh", ""),
            pinyin=s.get("pinyin", ""),
            part_of_speech=s.get("part_of_speech", ""),
            meaning_en=s.get("meaning_en", ""),
            meaning_zh=s.get("meaning_zh", ""),
            meaning_ne=s.get("meaning_ne", ""),
        )
        for s in raw.get("senses", [])
    ]
    first = senses[0] if senses else None
    return EntryOut(
        entry_id=raw.get("entry_id", ""),
        word_en=raw.get("word_en", ""),
        word_zh=raw.get("word_zh", "") or (first.word_zh if first else ""),
        senses=senses,
    )


def _from_entry(entry: EntryOut, surface: str) -> AnalyzedSegment:
    first = entry.senses[0] if entry.senses else None
    return AnalyzedSegment(
        surface=surface,
        kind="word",
        word_en=entry.word_en,
        word_zh=entry.word_zh,
        pinyin=(first.pinyin if first else ""),
        part_of_speech=(first.part_of_speech if first else ""),
        meaning_en=(first.meaning_en if first else ""),
        meaning_zh=(first.meaning_zh if first else ""),
        meaning_ne=(first.meaning_ne if first else ""),
        source="dataset",
    )


def _from_phrase(item: dict) -> AnalyzedSegment:
    surface = item.get("surface", item.get("key", ""))
    is_cjk = _is_cjk(surface)
    pos = item.get("pos", "")
    explicit = item.get("kind")
    if explicit:
        kind = explicit
    elif pos in ("phrase", "greeting"):
        kind = "phrase"
    elif len(surface) > 1 and is_cjk:
        kind = "compound"
    else:
        kind = "word"
    return AnalyzedSegment(
        surface=surface,
        kind=kind,
        word_en=item.get("word_en", ""),
        word_zh=surface if is_cjk else "",
        pinyin=item.get("pinyin", ""),
        part_of_speech=pos,
        meaning_en=item.get("meaning_en", ""),
        meaning_zh=item.get("meaning_zh", ""),
        meaning_ne=item.get("meaning_ne", ""),
        source="phrase",
        note=item.get("note", ""),
    )


def _is_cjk(s: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf" for c in s)


def _build_segments(text: str, lang: str) -> tuple[list[AnalyzedSegment], list[str]]:
    """Produce ordered segments; return (segments, unresolved_surfaces)."""
    index = _dataset_index()
    tokens = tokenize(text)
    surfaces = [t.surface for t in tokens]
    segments: list[AnalyzedSegment] = []
    unresolved: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if t.punct:
            segments.append(AnalyzedSegment(surface=t.surface, kind="punctuation"))
            i += 1
            continue

        # English idiom: longest match across consecutive Latin tokens.
        # Checked before the stopword filter — idioms often start with "a"/"the".
        if t.script == "lat":
            idiom, span = english_idiom_tokens(surfaces, i)
            if idiom and span >= 2:
                segments.append(_from_phrase(idiom))
                i += span
                continue
            if t.surface.lower() in _EN_STOPWORDS:
                segments.append(
                    AnalyzedSegment(
                        surface=t.surface, kind="function", source="stopword"
                    )
                )
                i += 1
                continue
            entry = index.get(t.surface.lower())
            if entry is not None:
                segments.append(_from_entry(entry, t.surface))
            else:
                segments.append(AnalyzedSegment(surface=t.surface, kind="word"))
                unresolved.append(t.surface)
            i += 1
            continue

        # Chinese: idiom (成语) → compound word → dataset word → single char.
        if t.script == "cjk":
            if t.surface in _CJK_STOPWORDS:
                segments.append(
                    AnalyzedSegment(
                        surface=t.surface, kind="function", source="stopword"
                    )
                )
                i += 1
                continue
            cid = cjk_idiom(t.surface)
            if cid:
                segments.append(_from_phrase(cid))
                i += 1
                continue
            cw = chinese_word(t.surface)
            if cw:
                segments.append(_from_phrase(cw))
                i += 1
                continue
            entry = index.get(t.surface)
            if entry is not None:
                segments.append(_from_entry(entry, t.surface))
            else:
                segments.append(AnalyzedSegment(surface=t.surface, kind="word"))
                unresolved.append(t.surface)
            i += 1
            continue

        # Numbers / other scripts: keep surface, no translation.
        segments.append(
            AnalyzedSegment(
                surface=t.surface,
                kind="word" if t.script == "num" else "other",
                source="unresolved",
            )
        )
        i += 1

    return segments, unresolved


def _apply_ai(seg: AnalyzedSegment, data: dict) -> None:
    """Copy an AI word entry onto a segment."""
    kind = data.get("kind") or "word"
    seg.kind = kind if kind in (
        "word", "compound", "phrase", "idiom", "other") else "word"
    seg.word_en = data.get("word_en", "")
    seg.word_zh = data.get("word_zh", "")
    seg.pinyin = data.get("pinyin", "")
    seg.part_of_speech = data.get("part_of_speech", "")
    seg.meaning_en = data.get("meaning_en", "")
    seg.meaning_zh = data.get("meaning_zh", "")
    seg.meaning_ne = data.get("meaning_ne", "")
    seg.source = "ai"


def _merge_ai_spans(
    segments: list[AnalyzedSegment], by_surface: dict[str, dict]
) -> list[AnalyzedSegment]:
    """Let the model treat consecutive units as one ("很" + "好" → "很好").

    Models often merge an adverb with its adjective on their own. Accept those
    spans so their meaning is not lost, without changing the offline segmenter.
    """
    out: list[AnalyzedSegment] = []
    i = 0
    n = len(segments)
    while i < n:
        span_match: tuple[int, dict] | None = None
        for span in range(min(4, n - i), 1, -1):
            group = segments[i:i + span]
            if any(s.kind in _NON_CONTENT_KINDS for s in group):
                continue
            cand = "".join(s.surface for s in group)
            data = by_surface.get(_norm(cand))
            if data:
                span_match = (span, data)
                break
        if span_match:
            span, data = span_match
            merged = AnalyzedSegment(surface="".join(
                s.surface for s in segments[i:i + span]))
            _apply_ai(merged, data)
            out.append(merged)
            i += span
        else:
            out.append(segments[i])
            i += 1
    return out


def analyze_text(text: str, lang: str) -> AnalyzeTextResponse:
    """Full pipeline. Safe for any input; never raises on AI failure."""
    clean = text.strip()
    if not clean:
        return AnalyzeTextResponse(text="", error="No translatable content found")

    lang_label = "zh" if any("\u4e00" <= c <= "\u9fff" for c in clean) else "en"
    segments, unresolved = _build_segments(clean, lang_label)

    meaningful_list = meaningful(tokenize(clean))
    mode: str = "paragraph"
    if len(meaningful_list) == 1:
        seg = segments[0] if segments else None
        mode = seg.kind if seg and seg.kind in (
            "word", "compound", "phrase", "idiom") else "word"

    # Deduplicate unresolved surfaces for the AI call (case-insensitively, so
    # "The" and "the" are a single unit).
    ai_surfaces = list(dict.fromkeys(_norm(s) for s in unresolved))[:_MAX_AI_SURFACES]

    whole = None
    degraded = False
    if ai_surfaces:
        ai = analyze_text_with_ai(clean, ai_surfaces, lang_label)
        if ai and ai.get("words"):
            by_surface = {_norm(k): v for k, v in ai["words"].items()}
            for seg in segments:
                data = by_surface.get(_norm(seg.surface))
                if seg.source == "unresolved" and data:
                    _apply_ai(seg, data)
            segments = _merge_ai_spans(segments, by_surface)
        whole_raw = (ai or {}).get("whole") or {}
        if any((whole_raw.get(k) or "").strip() for k in ("en", "zh", "ne")):
            whole = WholeTranslation(
                en=whole_raw.get("en", ""),
                zh=whole_raw.get("zh", ""),
                ne=whole_raw.get("ne", ""),
            )
        # Anything translatable still unresolved → degrade (AI missing/partial).
        degraded = any(
            s.source == "unresolved" and s.kind not in _NON_CONTENT_KINDS
            for s in segments
        )

    return AnalyzeTextResponse(
        text=clean,
        mode=mode,
        language=lang_label,
        segments=segments,
        whole=whole,
        degraded=degraded,
    )
