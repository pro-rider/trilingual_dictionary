from fastapi import APIRouter

from app.schemas.search import SentenceRequest, SentenceResponse
from app.services.sentence_generator import generate_sentence

router = APIRouter(tags=["sentence"])


@router.post("/search/sentence", response_model=SentenceResponse)
def sentence(req: SentenceRequest):
    return generate_sentence(req.sense_id, req.word)
