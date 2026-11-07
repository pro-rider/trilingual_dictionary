from fastapi import APIRouter

from app.core.security import SupabaseUser
from app.schemas.search import MeResponse

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=MeResponse)
def me(user: dict = SupabaseUser):
    """Return the authenticated Supabase user's identity (JWT-only, no DB)."""
    return MeResponse(uid=user["uid"], email=user["email"])
