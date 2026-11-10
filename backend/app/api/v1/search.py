from fastapi import APIRouter, Depends

from app.core import ai_guard
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search import dictionary_search_with_ai

router = APIRouter(tags=["search"])


@router.post(
    "/search",
    response_model=SearchResponse,
    dependencies=[Depends(ai_guard.require_ai_access), Depends(ai_guard.enforce_limits)],
)
def search(req: SearchRequest):
    entry = dictionary_search_with_ai(req.q, req.lang)
    return SearchResponse(query=req.q, lang=req.lang, entry=entry)
