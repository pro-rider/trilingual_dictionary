from typing import Literal

from fastapi import APIRouter, Query

from app.schemas.search import SuggestResponse
from app.services.search import suggest

router = APIRouter(tags=["suggest"])


@router.get("/suggest", response_model=SuggestResponse)
def suggestions(
    q: str = Query(..., min_length=1, max_length=80),
    lang: Literal["en", "zh"] = "en",
):
    return SuggestResponse(suggestions=suggest(q, lang))
