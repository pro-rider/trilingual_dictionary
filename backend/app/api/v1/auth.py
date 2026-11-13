from fastapi import APIRouter, HTTPException

from app.core import obs
from app.core.security import SupabaseUser
from app.schemas.auth import AccountDeleteRequest, AccountDeleteResponse
from app.schemas.search import MeResponse
from app.services.supabase_admin import (
    SupabaseAdmin,
    SupabaseAdminError,
    SupabaseUserNotFound,
)

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=MeResponse)
def me(user: dict = SupabaseUser):
    """Return the authenticated Supabase user's identity (JWT-only, no DB)."""
    return MeResponse(uid=user["uid"], email=user["email"])


@router.delete("/auth/account", response_model=AccountDeleteResponse)
def delete_account(payload: AccountDeleteRequest, user: dict = SupabaseUser):
    """Delete the caller's account: identity, sessions and profile.

    The Admin API deletes the `auth.users` row, which cascades to `profiles`
    (FK is `on delete cascade`) and invalidates every refresh token the user
    holds. There is no separate "delete sessions" step, because those sessions
    *are* the refresh tokens derived from that identity.
    """
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirmation required")

    admin = SupabaseAdmin()
    if not admin.configured:
        raise HTTPException(status_code=503, detail="Auth not configured")

    uid = user["uid"]
    already_absent = False
    try:
        admin.delete_user(uid)
    except SupabaseUserNotFound:
        # Deleting twice is a success: the account is gone either way.
        already_absent = True
    except SupabaseAdminError:
        # Status only — an upstream body can quote the address, and this is a
        # user-facing endpoint.
        obs.log_event(event="ACCOUNT_DELETE_FAILED", endpoint="/auth/account", status=502)
        raise HTTPException(status_code=502, detail="Account could not be deleted") from None

    obs.log_event(
        event="ACCOUNT_DELETED",
        endpoint="/auth/account",
        status=200,
        reason="already_absent" if already_absent else "deleted",
    )
    return AccountDeleteResponse(deleted=True, already_absent=already_absent)
