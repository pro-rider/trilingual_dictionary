from fastapi import APIRouter, Depends

from app.core import ai_guard
from app.text_analysis.analyzer import analyze_text
from app.text_analysis.schemas import AnalyzeTextRequest, AnalyzeTextResponse

router = APIRouter(tags=["analyze"])


@router.post(
    "/analyze/text",
    response_model=AnalyzeTextResponse,
    dependencies=[Depends(ai_guard.require_ai_access), Depends(ai_guard.enforce_limits)],
)
def analyze(req: AnalyzeTextRequest) -> AnalyzeTextResponse:
    """Analyze a word / phrase / sentence / paragraph into per-unit meanings.

    Single words, compound words, phrases and idioms each get their own
    trilingual meaning (English / 中文 / नेपाली). Degrades gracefully when AI
    is unavailable.
    """
    return analyze_text(req.text, req.lang)
