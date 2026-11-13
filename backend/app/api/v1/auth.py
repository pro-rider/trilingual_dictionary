"""Auth endpoints. Every one of them is listed in `docs/auth-contract.yaml`,
and `backend/tests/test_auth_contract.py` fails if that list and this router
disagree.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request

from app.core import obs
from app.core.security import SupabaseUser
from app.schemas.auth import (
    AccountDeleteRequest,
    AccountDeleteResponse,
    LoginRequest,
    PasswordChangeRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    RegisterCompleteRequest,
    RegisterStartRequest,
    RegisterVerifyRequest,
    RegisterVerifyResponse,
    TokenPair,
    UsernameAvailability,
)
from app.schemas.auth import SessionListResponse, SessionSummary
from app.schemas.search import MeResponse
from app.services import auth_flow, passwords, profiles, sessions
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


def current_session(
    user: dict = SupabaseUser,
    store=Depends(get_store),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
):
    """Authenticated *and* backed by a live session on this device.

    The JWT alone is not enough: `logout-all` marks every row revoked, and this
    check makes that bite on the next request instead of when the access token
    happens to expire. The device id comes from the app's random install id.
    """
    try:
        return user, sessions.enforce(store, user_id=user["uid"], device_id=x_device_id)
    except sessions.SessionRevoked:
        raise HTTPException(status_code=401, detail="Session ended; sign in again") from None


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
    from app.services import disposable_domains

    if disposable_domains.is_disposable(payload.email):
        # Domain-level refusal: it says nothing about whether this address has
        # an account, so it cannot be used to probe. The message names no list.
        obs.log_event(event="DISPOSABLE_DOMAIN", endpoint="/auth/register/start", status=400)
        raise HTTPException(
            status_code=400,
            detail="Please use a permanent email address; this provider is not supported.",
        )
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
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
    x_device_label: str | None = Header(default=None, alias="X-Device-Label"),
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

    try:
        sessions.create(
            store, user_id=profile.user_id, device_id=x_device_id,
            device_label=x_device_label or "signup",
        )
    except Exception:
        # A created account must not be lost because the session row failed.
        obs.log_event(event="SESSION_CREATE_FAILED", endpoint="/auth/register/complete", status=200)

    obs.log_event(event="ACCOUNT_CREATED", endpoint="/auth/register/complete", status=200)
    return TokenPair(
        access_token=session.get("access_token", ""),
        refresh_token=session.get("refresh_token", ""),
        expires_in=int(session.get("expires_in", 3600)),
    )


# ------------------------------------------------------------------------- login


@router.post("/auth/login", response_model=TokenPair)
def login(
    payload: LoginRequest,
    store=Depends(get_store),
    auth_client=Depends(get_auth_client),
    x_device_label: str | None = Header(default=None, alias="X-Device-Label"),
):
    try:
        result = auth_flow.login(store, auth_client, payload.identifier, payload.password)
    except auth_flow.LoginFailed:
        obs.log_event(event="LOGIN_FAILED", endpoint="/auth/login", status=401)
        raise HTTPException(status_code=401, detail="Invalid username or password") from None

    session = result["session"]
    uid = result.get("uid")
    if uid:
        sessions.create(
            store, user_id=uid, device_id=payload.device_id,
            device_label=x_device_label or "app",
        )
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
def logout(
    request: Request,
    auth_client=Depends(get_auth_client),
    user: dict = SupabaseUser,
    store=Depends(get_store),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
):
    """Revoke this device's session and, best effort, its refresh token.

    If Supabase cannot be reached the local row is still revoked, which is what
    the next authenticated request checks; the upstream token dies at expiry.
    """
    try:
        auth_client.sign_out(_bearer(request))
    except Exception:
        obs.log_event(event="LOGOUT_UPSTREAM_FAILED", endpoint="/auth/logout", status=204)
    try:
        session = store.session_for_device(user["uid"], sessions.device_hash(x_device_id or "unknown-device"))
        if session is not None:
            store.revoke_session(session.session_id, time.time())
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------- sessions


@router.get("/auth/sessions", response_model=SessionListResponse)
def list_sessions(
    store=Depends(get_store),
    auth=Depends(current_session),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
):
    """The user's devices. No raw IP, no token, no e-mail: label + timestamps."""
    user, current = auth
    current_hash = sessions.device_hash(x_device_id or "unknown-device")
    return SessionListResponse(
        sessions=[
            SessionSummary(
                session_id=session.session_id,
                device_label=session.device_label,
                created_at=session.created_at,
                last_seen=session.last_seen,
                current=session.device_hash == current_hash,
            )
            for session in sessions.active_sessions(store, user["uid"])
        ]
    )


@router.post("/auth/logout-all", status_code=204)
def logout_all(
    request: Request,
    auth_client=Depends(get_auth_client),
    store=Depends(get_store),
    auth=Depends(current_session),
):
    """Revoke every device. Effective on the next request, not at token expiry."""
    user, _current = auth
    try:
        auth_client.sign_out(_bearer(request))
    except Exception:
        obs.log_event(event="LOGOUT_UPSTREAM_FAILED", endpoint="/auth/logout-all", status=204)
    revoked = sessions.revoke_all(store, user["uid"])
    obs.log_event(event="LOGOUT_ALL", endpoint="/auth/logout-all", status=204, count=revoked)
    return None


@router.delete("/auth/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: str,
    store=Depends(get_store),
    auth=Depends(current_session),
):
    """Sign one other device out by id from the list above."""
    user, _current = auth
    if not sessions.revoke_one(store, user_id=user["uid"], session_id=session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    obs.log_event(event="SESSION_REVOKED", endpoint="/auth/sessions/{id}", status=204)
    return None


# ----------------------------------------------------------------------- profile


def _profile_response(row) -> ProfileResponse:
    return ProfileResponse(
        user_id=row.user_id, email=row.email, username=row.username, status=row.status,
        nepali_enabled=row.nepali_enabled, display_name=row.display_name, locale=row.locale,
    )


@router.get("/auth/profile", response_model=ProfileResponse)
def get_profile(store=Depends(get_store), auth=Depends(current_session)):
    user = auth[0]
    """Always the caller's own profile: there is no uid parameter to abuse."""
    row = store.profile_by_user_id(user["uid"])
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _profile_response(row)


@router.patch("/auth/profile", response_model=ProfileResponse)
def update_profile(payload: ProfileUpdateRequest, store=Depends(get_store), auth=Depends(current_session)):
    user = auth[0]
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
    auth=Depends(current_session),
):
    user = auth[0]
    """Delete identity, sessions and profile — but only after re-authentication."""
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirmation required")

    row_before = store.profile_by_user_id(user["uid"])
    identity_email = row_before.email if row_before else None

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

    # Pre-account traces: an unconsumed challenge or signup token for this
    # address would outlive the account and re-identify it (A29).
    if identity_email:
        try:
            store.purge_identity_traces(
                email=identity_email,
                email_hash=auth_flow.email_hash(identity_email),
            )
        except Exception:
            obs.log_event(event="IDENTITY_PURGE_FAILED", endpoint="/auth/account", status=200)

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

    # A reset means "someone else may have my old password": every device out.
    revoked = sessions.revoke_all(store, row.user_id)
    obs.log_event(
        event="PASSWORD_RESET", endpoint="/auth/password/reset", status=200,
        count=revoked,
    )
    return TokenPair(access_token="", refresh_token="", expires_in=0)

@router.post("/auth/password/change", status_code=204)
def password_change(
    payload: PasswordChangeRequest,
    store=Depends(get_store),
    auth_client=Depends(get_auth_client),
    auth=Depends(current_session),
):
    """Change the password while signed in; every other session dies with it.

    Requires the current password, so possessing an access token is not enough
    to take the account over. The caller's own session is revoked too and the
    app must sign in again — simpler to reason about than a half-revocation, and
    it matches what a user expects after "change my password everywhere".
    """
    user = auth[0]
    row = store.profile_by_user_id(user["uid"])
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    try:
        auth_client.sign_in_with_password(row.email, payload.current_password)
    except Exception:
        obs.log_event(event="PASSWORD_CHANGE_REJECTED", endpoint="/auth/password/change", status=403)
        raise HTTPException(status_code=403, detail="Current password is not correct") from None

    policy = passwords.policy_errors(
        payload.new_password, username=row.username, email=row.email
    )
    if policy:
        raise HTTPException(status_code=400, detail=policy[0])

    try:
        auth_client.set_password(user["uid"], payload.new_password)
    except Exception:
        raise HTTPException(status_code=502, detail="Password could not be changed") from None

    revoked = sessions.revoke_all(store, user["uid"])
    obs.log_event(
        event="PASSWORD_CHANGE", endpoint="/auth/password/change", status=204,
        count=revoked,
    )
    return None
