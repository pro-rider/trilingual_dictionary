"""Auth endpoints. Every one of them is listed in `docs/auth-contract.yaml`,
and `backend/tests/test_auth_contract.py` fails if that list and this router
disagree.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from app.core import obs
from app.core.security import SupabaseUser
from app.schemas.auth import (
    AccountDeleteRequest,
    AccountDeleteResponse,
    LoginRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    RegisterCompleteRequest,
    RegisterStartRequest,
    RegisterVerifyRequest,
    RegisterVerifyResponse,
    TokenPair,
    UsernameAvailability,
)
from app.schemas.search import MeResponse
from app.services import auth_flow, passwords, profiles
from app.services.auth_store import PgAuthStore
from app.services.mailer import get_mailer
from app.services.supabase_admin import (
    SupabaseAdmin,
    SupabaseAdminError,
    SupabaseUserNotFound,
)
from app.services.supabase_auth import SupabaseAuthClient

router = APIRouter(tags=["auth"])

_store: PgAuthStore | None = None


def get_store() -> PgAuthStore:
    global _store
    if _store is None:
        _store = PgAuthStore()
    return _store


def get_admin() -> SupabaseAdmin:
    return SupabaseAdmin()


def get_auth_client() -> SupabaseAuthClient:
    return SupabaseAuthClient()


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


# ------------------------------------------------------------------ registration


@router.post("/auth/register/start", status_code=202)
def register_start(
    payload: RegisterStartRequest,
    background: BackgroundTasks,
    store=Depends(get_store),
):
    """Always 202 with an identical body. Mail goes out in the background.

    A synchronous send would make the response time depend on whether a code
    already existed for this address, which is the timing leak called out in
    review. Both paths therefore schedule the same background task.
    """
    result = auth_flow.register_start(store, payload.email)
    if result.code is not None:
        background.add_task(get_mailer().send_code, result.email, result.code)
    obs.log_event(event="REGISTER_START", endpoint="/auth/register/start", status=202)
    return {"detail": "If the address can receive mail, a code is on its way."}


@router.post("/auth/register/verify", response_model=RegisterVerifyResponse)
def register_verify(payload: RegisterVerifyRequest, store=Depends(get_store)):
    result = auth_flow.register_verify(store, payload.email, payload.code)
    if not result.ok:
        if result.reason == "too_many_attempts":
            obs.log_event(event="CODE_BRUTEFORCE", endpoint="/auth/register/verify", status=400)
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    return RegisterVerifyResponse(signup_token=result.signup_token, expires_in=result.expires_in)


@router.post("/auth/register/complete", response_model=TokenPair)
def register_complete(
    payload: RegisterCompleteRequest,
    store=Depends(get_store),
    admin=Depends(get_admin),
    auth_client=Depends(get_auth_client),
):
    try:
        profile = auth_flow.register_complete(
            store, admin,
            signup_token=payload.signup_token,
            username=payload.username,
            password=payload.password,
        )
    except PermissionError:
        raise HTTPException(status_code=401, detail="Verification expired; request a new code") from None
    except auth_flow.RegisterConflict:
        raise HTTPException(status_code=409, detail="That username is not available") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    try:
        session = auth_client.sign_in_with_password(profile.email, payload.password)
    except Exception:
        raise HTTPException(
            status_code=502, detail="Account created but sign-in failed; try logging in"
        ) from None

    obs.log_event(event="ACCOUNT_CREATED", endpoint="/auth/register/complete", status=200)
    return TokenPair(
        access_token=session.get("access_token", ""),
        refresh_token=session.get("refresh_token", ""),
        expires_in=int(session.get("expires_in", 3600)),
    )


# ------------------------------------------------------------------------- login


@router.post("/auth/login", response_model=TokenPair)
def login(payload: LoginRequest, store=Depends(get_store), auth_client=Depends(get_auth_client)):
    try:
        result = auth_flow.login(store, auth_client, payload.identifier, payload.password)
    except auth_flow.LoginFailed:
        obs.log_event(event="LOGIN_FAILED", endpoint="/auth/login", status=401)
        raise HTTPException(status_code=401, detail="Invalid username or password") from None

    session = result["session"]
    obs.log_event(event="LOGIN_OK", endpoint="/auth/login", status=200)
    return TokenPair(
        access_token=session.get("access_token", ""),
        refresh_token=session.get("refresh_token", ""),
        expires_in=int(session.get("expires_in", 3600)),
    )


@router.post("/auth/refresh", response_model=TokenPair)
def refresh(payload: dict, auth_client=Depends(get_auth_client)):
    token = str(payload.get("refresh_token") or "")
    if not token:
        raise HTTPException(status_code=400, detail="refresh_token required")
    try:
        session = auth_client.refresh(token)
    except Exception:
        obs.log_event(event="TOKEN_REUSE", endpoint="/auth/refresh", status=401)
        raise HTTPException(status_code=401, detail="Session expired") from None
    return TokenPair(
        access_token=session.get("access_token", ""),
        refresh_token=session.get("refresh_token", ""),
        expires_in=int(session.get("expires_in", 3600)),
    )


@router.post("/auth/logout", status_code=204)
def logout(request: Request, auth_client=Depends(get_auth_client), user: dict = SupabaseUser):
    """Revoke this session's refresh token. Best effort: the token may be dead."""
    try:
        auth_client.sign_out(_bearer(request))
    except Exception:
        pass
    return None


# ----------------------------------------------------------------------- profile


def _profile_response(row) -> ProfileResponse:
    return ProfileResponse(
        user_id=row.user_id, email=row.email, username=row.username, status=row.status,
        nepali_enabled=row.nepali_enabled, display_name=row.display_name, locale=row.locale,
    )


@router.get("/auth/profile", response_model=ProfileResponse)
def get_profile(store=Depends(get_store), user: dict = SupabaseUser):
    """Always the caller's own profile: there is no uid parameter to abuse."""
    row = store.profile_by_user_id(user["uid"])
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _profile_response(row)


@router.patch("/auth/profile", response_model=ProfileResponse)
def update_profile(payload: ProfileUpdateRequest, store=Depends(get_store), user: dict = SupabaseUser):
    fields = profiles.validate_profile_update(payload.model_dump(exclude_none=True))
    store.update_profile(user["uid"], fields)
    row = store.profile_by_user_id(user["uid"])
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _profile_response(row)


@router.get("/auth/username/available", response_model=UsernameAvailability)
def username_available(username: str = Query(min_length=3, max_length=20), store=Depends(get_store)):
    normalized = profiles.normalize_username(username)
    if profiles.username_shape_errors(normalized):
        return UsernameAvailability(available=False)
    return UsernameAvailability(available=not store.username_taken(normalized))


# ----------------------------------------------------------------------- account


@router.get("/me", response_model=MeResponse)
def me(user: dict = SupabaseUser):
    return MeResponse(uid=user["uid"], email=user["email"])


@router.delete("/auth/account", response_model=AccountDeleteResponse)
def delete_account(
    payload: AccountDeleteRequest,
    store=Depends(get_store),
    admin=Depends(get_admin),
    auth_client=Depends(get_auth_client),
    user: dict = SupabaseUser,
):
    """Delete identity, sessions and profile — but only after re-authentication."""
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirmation required")

    try:
        auth_flow.delete_account(
            store, admin, auth_client,
            uid=user["uid"], password=payload.password, code=payload.code,
        )
    except auth_flow.ReauthRequired:
        obs.log_event(event="ACCOUNT_DELETE_REAUTH_FAILED", endpoint="/auth/account", status=403)
        raise HTTPException(status_code=403, detail="Re-authentication failed") from None
    except SupabaseAdminError:
        obs.log_event(event="ACCOUNT_DELETE_FAILED", endpoint="/auth/account", status=502)
        raise HTTPException(status_code=502, detail="Account could not be deleted") from None
    except SupabaseUserNotFound:
        pass

    obs.log_event(event="ACCOUNT_DELETED", endpoint="/auth/account", status=200)
    return AccountDeleteResponse(deleted=True)


# ---------------------------------------------------------------------- password


@router.post("/auth/password/forgot", status_code=202)
def password_forgot(
    payload: RegisterStartRequest,
    background: BackgroundTasks,
    store=Depends(get_store),
):
    """Same envelope as register/start: the response must not reveal state."""
    result = auth_flow.register_start(store, payload.email, purpose="reset")
    if result.code is not None:
        background.add_task(get_mailer().send_code, result.email, result.code)
    return {"detail": "If the address can receive mail, a code is on its way."}


@router.post("/auth/password/reset", response_model=TokenPair)
def password_reset(
    payload: dict,
    store=Depends(get_store),
    auth_client=Depends(get_auth_client),
):
    """A verified reset code plus a new password; Supabase performs the change."""
    email = str(payload.get("email") or "").strip().lower()
    code = str(payload.get("code") or "")
    new_password = str(payload.get("password") or "")
    if not email or not code or not new_password:
        raise HTTPException(status_code=400, detail="email, code and password are required")

    result = auth_flow.register_verify(store, email, code, purpose="reset")
    if not result.ok:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    policy = passwords.policy_errors(new_password, email=email)
    if policy:
        raise HTTPException(status_code=400, detail=policy[0])

    row = store.profile_by_email(email)
    if row is None:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    try:
        auth_client.set_password(row.user_id, new_password)
    except Exception:
        raise HTTPException(status_code=502, detail="Password could not be changed") from None

    obs.log_event(event="PASSWORD_RESET", endpoint="/auth/password/reset", status=200)
    return TokenPair(access_token="", refresh_token="", expires_in=0)
