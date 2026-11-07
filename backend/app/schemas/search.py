from typing import Literal, Optional

from pydantic import BaseModel, Field


class ExampleSentenceOut(BaseModel):
    en: str
    zh: str
    ne: str
    source: str = "reviewed"
    review_status: str = "approved"


class SenseOut(BaseModel):
    sense_id: str
    word_en: str
    word_zh: str
    pinyin: str = ""
    ipa_en: str = ""
    part_of_speech: str = ""
    meaning_en: str
    meaning_zh: str
    meaning_ne: str
    meaning_ne_status: str = "published"
    examples: list[ExampleSentenceOut] = Field(default_factory=list)


class EntryOut(BaseModel):
    entry_id: str
    word_en: str
    word_zh: str
    senses: list[SenseOut] = Field(default_factory=list)
    # Provenance: "dictionary" (curated fixture or merged SQLite) or "ai"
    # (generated on the fly because nothing matched). The client must label
    # `source == "ai"` results as unverified rather than as dictionary facts.
    source: str = "dictionary"
    unverified: bool = False
    cached: bool = False


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=80)
    lang: Literal["en", "zh"] = "en"


class SearchResponse(BaseModel):
    query: str
    lang: str
    entry: Optional[EntryOut] = None


class SentenceRequest(BaseModel):
    sense_id: str = ""
    word: str = Field(..., min_length=1)


class SentenceResponse(BaseModel):
    sense_id: str
    word: str
    en: str
    zh: str
    ne: str
    source: str = "fallback"
    review_status: str = "unreviewed"


class PopularResponse(BaseModel):
    words: list[str] = Field(default_factory=list)


class SuggestRequest(BaseModel):
    q: str = Field(..., min_length=1)
    lang: Literal["en", "zh"] = "en"


class SuggestResponse(BaseModel):
    suggestions: list[str] = Field(default_factory=list)


class MeResponse(BaseModel):
    uid: str
    email: str = ""


class FavoritesResponse(BaseModel):
    entry_ids: list[str] = Field(default_factory=list)


class FavoriteAddRequest(BaseModel):
    entry_id: str = Field(..., min_length=1, max_length=120)


class FeedbackRequest(BaseModel):
    sense_id: str = Field(..., min_length=1)
    field: str = Field(default="meaning", max_length=40)
    comment: str = Field(default="", max_length=2000)


class FeedbackResponse(BaseModel):
    id: int
    status: str
