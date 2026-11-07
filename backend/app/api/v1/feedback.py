from fastapi import APIRouter

from app.api.deps import DbSession
from app.core.security import SupabaseUser
from app.models.cloud import Feedback
from app.schemas.search import FeedbackRequest, FeedbackResponse

router = APIRouter(tags=["feedback"])


@router.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(
    req: FeedbackRequest, db: DbSession, user: dict = SupabaseUser
):
    """Record a user-reported error → status 'flagged' → review queue."""
    row = Feedback(
        user_id=user["uid"],
        sense_id=req.sense_id,
        field=req.field,
        comment=req.comment,
        status="flagged",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return FeedbackResponse(id=row.id, status=row.status)
