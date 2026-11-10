"""On-demand enrichment: Nepali gloss + one example sentence per sense.

The packaged dictionary ships with CC-CEDICT's Chinese+English only. Rather
than paying for 195k senses up front (measured 0.4 senses/s on free-tier keys —
about 5 days), the app asks for exactly the senses a learner actually opens and
writes the answer back into its own on-device database, so the second lookup is
free and offline.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

MAX_ITEMS = 20

# Per-field caps: the request is forwarded to a paid-or-free LLM, so an unbounded
# string here is unbounded prompt cost. Generous for real glosses, fatal for abuse.
MAX_KEY = 64
MAX_GLOSS = 200

_CONTROL_CHARS = dict.fromkeys(range(0x20), None)  # C0 controls incl. \n, \r, \t
_CONTROL_CHARS.update(dict.fromkeys(range(0x7F, 0xA0), None))


def _clean(v: str) -> str:
    """Strip control characters and surrounding whitespace, keep printable text."""
    return (v or "").translate(_CONTROL_CHARS).strip()


class EnrichItem(BaseModel):
    key: str = Field(..., max_length=MAX_KEY)
    zh: str = Field(default="", max_length=MAX_GLOSS)
    en: str = Field(default="", max_length=MAX_GLOSS)

    @field_validator("key", "zh", "en")
    @classmethod
    def _strip_controls(cls, v: str) -> str:
        return _clean(v)


class EnrichRequest(BaseModel):
    items: list[EnrichItem] = Field(default_factory=list, max_length=MAX_ITEMS)


class EnrichItemOut(BaseModel):
    key: str
    zh: str = ""
    ne: str = ""
    example_en: str = ""
    example_zh: str = ""
    example_ne: str = ""


class EnrichResponse(BaseModel):
    items: list[EnrichItemOut] = Field(default_factory=list)
    provider: str = ""
