from fastapi import APIRouter

from app.text_analysis.analyzer import analyze_text
from app.text_analysis.schemas import AnalyzeTextRequest, AnalyzeTextResponse

router = APIRouter(tags=["analyze"])


@router.post("/analyze/text", response_model=AnalyzeTextResponse)
def analyze(req: AnalyzeTextRequest) -> AnalyzeTextResponse:
    """Analyze a word / phrase / sentence / paragraph into per-unit meanings.

    Single words, compound words, phrases and idioms each get their own
    trilingual meaning (English / 中文 / नेपाली). Degrades gracefully when AI
    is unavailable.
    """
    return analyze_text(req.text, req.lang)
