from fastapi import APIRouter, Depends

from app.ai.provider import enrich_senses_batch
from app.core import ai_guard
from app.schemas.dictionary import (
    MAX_ITEMS,
    EnrichItemOut,
    EnrichRequest,
    EnrichResponse,
)

router = APIRouter(tags=["dictionary"])


@router.post(
    "/dictionary/enrich",
    response_model=EnrichResponse,
    dependencies=[Depends(ai_guard.require_ai_access), Depends(ai_guard.enforce_limits)],
)
def enrich(req: EnrichRequest):
    """Fill the gaps CC-CEDICT leaves: Nepali gloss + one example sentence.

    The app calls this with the senses it just displayed that have no Nepali
    text, then writes the result into its own SQLite file. Cheap because it
    only ever covers words somebody actually looked at.
    """
    items = req.items[:MAX_ITEMS]
    if not items:
        return EnrichResponse(items=[])
    payload = enrich_senses_batch([(i.key, i.zh, i.en) for i in items])
    return EnrichResponse(
        items=[
            EnrichItemOut(
                key=item.key,
                zh=payload.get(item.key, {}).get("zh", ""),
                ne=payload.get(item.key, {}).get("ne", ""),
                example_en=payload.get(item.key, {}).get("example_en", ""),
                example_zh=payload.get(item.key, {}).get("example_zh", ""),
                example_ne=payload.get(item.key, {}).get("example_ne", ""),
            )
            for item in items
        ]
    )
