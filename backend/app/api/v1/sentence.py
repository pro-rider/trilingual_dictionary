from fastapi import APIRouter, Depends

from app.core import ai_guard
from app.schemas.search import SentenceRequest, SentenceResponse
from app.services.sentence_generator import generate_sentence

router = APIRouter(tags=["sentence"])


@router.post(
    "/search/sentence",
    response_model=SentenceResponse,
    dependencies=[Depends(ai_guard.require_ai_access), Depends(ai_guard.enforce_limits)],
)
def sentence(req: SentenceRequest):
    # This route can reach generate_draft(), i.e. a real model call, so it
    # declares the same guard + limiter pair as /search, /analyze/text and
    # /dictionary/enrich. Leaving it unguarded would let a client spend the free
    # quota (and write AI cache rows) without the shared token.
    return generate_sentence(req.sense_id, req.word)
