"""The registration and login flow, independent of HTTP.

Everything that must be provable is decided here:

* **No identity exists before the code is verified.** `register_start` only
  writes a challenge row (email hash + code hash). No `auth.users` row, no
  profile, no password. That is what makes pre-account takeover impossible rather
  than merely unlikely.
* **The send cap never invalidates a live code.** Burning the hourly quota
  stops new mail, and an already-delivered, unexpired code still verifies. The
  victim's inbox is theirs, so the code that reached it is proof of ownership.
* **Both register branches do the same work.** The router schedules the mail
  send as a background task on both paths, so the response never waits on SMTP.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from app.core.config import settings
from app.services import otp, passwords, profiles
from app.services.auth_store import AuthStore, Challenge, ProfileRow


@dataclass
class StartResult:
    email: str
    code: str | None          # None means "nothing sent", not "error"
    retry_after: int | None = None


@dataclass
class VerifyResult:
    ok: bool
    signup_token: str | None = None
    expires_in: int = 0
    reason: str = "invalid_or_expired"


class RegisterConflict(Exception):
    pass


class AuthNotConfigured(Exception):
    """No pepper means a 6-digit code is brute-forceable from a DB dump."""


def pepper() -> str:
    value = settings.auth_code_pepper
    if len(value) < 16:
        raise AuthNotConfigured("AUTH_CODE_PEPPER must be set")
    return value


def email_hash(email: str) -> str:
    return hashlib.sha256(f"auth-email:{email.strip().lower()}:{pepper()}".encode()).hexdigest()


def register_start(store: AuthStore, email: str, *, purpose: str = "signup", now: float | None = None) -> StartResult:
    now = now or time.time()
    key = email_hash(email)
    challenge = store.get_challenge(key, purpose)

    if challenge is not None and now - challenge.window_started_at >= settings.auth_send_window_seconds:
        challenge.sends_in_window = 0
        challenge.window_started_at = now

    if challenge is not None and challenge.attempts >= settings.auth_max_code_attempts:
        # The code is dead; a new one would be a way around the attempt budget.
        return StartResult(email=email, code=None, retry_after=settings.auth_resend_cooldown_seconds)

    if challenge is not None and challenge.sends_in_window >= settings.auth_max_emails_per_hour:
        # Quota exhausted: no new mail, but the existing code stays valid.
        return StartResult(email=email, code=None, retry_after=settings.auth_send_window_seconds)

    code = otp.issue_code()
    new_challenge = Challenge(
        email_hash=key,
        code_hash=otp.hash_code(code, pepper()),
        expires_at=now + settings.auth_code_ttl_minutes * 60,
        purpose=purpose,
        attempts=0,
        sends_in_window=(challenge.sends_in_window if challenge else 0) + 1,
        window_started_at=(challenge.window_started_at if challenge else now),
    )
    store.put_challenge(new_challenge)
    return StartResult(email=email, code=code)


def register_verify(store: AuthStore, email: str, raw_code: str, *, purpose: str = "signup",
                    now: float | None = None) -> VerifyResult:
    now = now or time.time()
    key = email_hash(email)
    challenge = store.get_challenge(key, purpose)

    if challenge is None:
        return VerifyResult(ok=False, reason="invalid_or_expired")
    if challenge.attempts >= settings.auth_max_code_attempts:
        return VerifyResult(ok=False, reason="too_many_attempts")
    if now > challenge.expires_at:
        return VerifyResult(ok=False, reason="invalid_or_expired")

    submitted = otp.normalize_code(raw_code)
    if submitted is None or not otp.code_matches(
        submitted, challenge.code_hash, pepper()
    ):
        store.bump_attempts(key, purpose)
        return VerifyResult(ok=False, reason="invalid_or_expired")

    store.delete_challenge(key, purpose)
    token = otp.issue_token()
    ttl = settings.auth_signup_token_ttl_seconds
    store.save_signup_token(otp.hash_token(token), email.strip().lower(), now + ttl)
    return VerifyResult(ok=True, signup_token=token, expires_in=ttl)


def register_complete(
    store: AuthStore,
    admin,
    *,
    signup_token: str,
    username: str,
    password: str,
) -> ProfileRow:
    email = store.take_signup_token(otp.hash_token(signup_token))
    if not email:
        raise PermissionError("signup token invalid or expired")

    normalized = profiles.normalize_username(username)
    problems = profiles.username_shape_errors(normalized)
    if problems:
        raise ValueError(problems[0])
    if profiles.is_reserved(normalized):
        raise ValueError("that username is reserved")
    if store.username_taken(normalized):
        raise RegisterConflict("username unavailable")

    policy = passwords.policy_errors(password, username=normalized, email=email)
    if policy:
        raise ValueError(policy[0])
    if passwords.is_breached(password):
        raise ValueError("that password appears in a known breach; choose another")

    created = admin.create_user(email=email, password=password)
    uid = created["id"]
    profile = ProfileRow(
        user_id=uid, email=email, username=normalized, status="active",
        display_name=None, locale="en", nepali_enabled=True,
    )
    store.create_profile(profile)
    return profile


class LoginFailed(Exception):
    pass


def login(store: AuthStore, auth_client, identifier: str, password: str, device_id: str | None = None):
    """One password grant for both identifier shapes.

    A username that matches nothing is resolved to a fixed placeholder address
    so the same upstream call happens on every path; the caller always answers
    "Invalid username or password".
    """
    identifier = identifier.strip()
    if "@" in identifier:
        email = identifier.lower()
        username = None
    else:
        row = store.profile_by_username(profiles.normalize_username(identifier))
        email = row.email if row else "unknown@invalid.local"
        username = row.username if row else profiles.normalize_username(identifier)

    try:
        session = auth_client.sign_in_with_password(email, password)
    except Exception:
        raise LoginFailed("Invalid username or password") from None

    uid = (session.get("user") or {}).get("id")
    row = store.profile_by_user_id(uid) if uid else None
    if row is not None and row.status != "active":
        # A verified email without a username is not a usable account.
        raise LoginFailed("Invalid username or password")

    return {"session": session, "uid": uid, "username": username}


class ReauthRequired(Exception):
    pass


def delete_account(store: AuthStore, admin, auth_client, *, uid: str, password: str | None,
                   code: str | None) -> None:
    """Delete only after proving possession.

    A stolen access token must not be enough: the caller supplies the password
    (verified by Supabase, so we never see stored hashes) or a fresh emailed
    code. Events are anonymised rather than deleted, because the aggregate
    security signal outlives the account.
    """
    row = store.profile_by_user_id(uid)
    email = row.email if row else None

    if password and email:
        try:
            auth_client.sign_in_with_password(email, password)
        except Exception:
            raise ReauthRequired("re-authentication failed") from None
    elif code and email:
        result = register_verify(store, email, code, purpose="reset")
        if not result.ok:
            raise ReauthRequired("re-authentication failed")
    else:
        raise ReauthRequired("re-authentication required")

    try:
        admin.delete_user(uid)
    except Exception as exc:
        if exc.__class__.__name__ != "SupabaseUserNotFound":
            raise

    # The FK cascade already removes the row in Postgres; this also covers the
    # in-memory store the tests use, and a project where the cascade is missing.
    store.delete_profile(uid)
    store.anonymize_events(uid)
