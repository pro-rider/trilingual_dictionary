from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

SegmentKind = Literal[
    "word", "compound", "phrase", "idiom", "punctuation", "function", "other"
]
SegmentSource = Literal["dataset", "phrase", "ai", "unresolved", "stopword"]


class AnalyzeTextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    lang: Literal["en", "zh", "auto"] = "auto"


class AnalyzedSegment(BaseModel):
    """One piece of the analyzed text with its own trilingual meaning."""

    surface: str = ""
    kind: SegmentKind = "word"
    word_en: str = ""
    word_zh: str = ""
    pinyin: str = ""
    part_of_speech: str = ""
    meaning_en: str = ""
    meaning_zh: str = ""
    meaning_ne: str = ""
    source: SegmentSource = "unresolved"
    note: str = ""


class WholeTranslation(BaseModel):
    en: str = ""
    zh: str = ""
    ne: str = ""


class AnalyzeTextResponse(BaseModel):
    text: str = ""
    mode: Literal["word", "compound", "phrase", "idiom", "paragraph"] = "paragraph"
    language: Literal["en", "zh"] = "en"
    segments: list[AnalyzedSegment] = Field(default_factory=list)
    whole: Optional[WholeTranslation] = None
    degraded: bool = False
    error: str = ""
