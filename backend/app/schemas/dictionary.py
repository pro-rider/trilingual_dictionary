"""On-demand enrichment: Nepali gloss + one example sentence per sense.

The packaged dictionary ships with CC-CEDICT's Chinese+English only. Rather
than paying for 195k senses up front (measured 0.4 senses/s on free-tier keys —
about 5 days), the app asks for exactly the senses a learner actually opens and
writes the answer back into its own on-device database, so the second lookup is
free and offline.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_ITEMS = 20


class EnrichItem(BaseModel):
    key: str
    zh: str = ""
    en: str = ""


class EnrichRequest(BaseModel):
    items: list[EnrichItem] = Field(default_factory=list)


class EnrichItemOut(BaseModel):
    key: str
    ne: str = ""
    example_en: str = ""
    example_zh: str = ""
    example_ne: str = ""


class EnrichResponse(BaseModel):
    items: list[EnrichItemOut] = Field(default_factory=list)
    provider: str = ""
