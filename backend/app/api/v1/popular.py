from fastapi import APIRouter

from app.schemas.search import PopularResponse
from app.services.search import popular_words

router = APIRouter(tags=["popular"])


@router.get("/popular", response_model=PopularResponse)
def popular(limit: int = 6):
    return PopularResponse(words=popular_words(limit))
