"""FastAPI-owned sessions.

Why we own them: Supabase's free plan does not give per-device session listing,
and its session time-boxing / inactivity timeout are not available to us. A
stolen refresh token would otherwise stay usable until the user happened to
notice. With this table we can list a user's devices, revoke one, revoke all,
and enforce two clocks (A30):

* **idle** — no authenticated request for 7 days retires the session;
* **absolute** — 30 days after creation, regardless of activity.

Enforcement happens on every authenticated request, because the dependency
looks the row up by the caller's device id and refuses a revoked, idle or
overtime session. That is what makes "log out all devices" true immediately
instead of "true after the access token expires".

We never store a refresh token or an IP: the device id is the app's random
install id, kept only as a SHA-256 hash.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

from app.core.config import settings


def device_hash(device_id: str) -> str:
    return hashlib.sha256(f"device:{device_id.strip()}".encode()).hexdigest()


def new_session_id() -> str:
    return secrets.token_urlsafe(24)


def new_family_id() -> str:
    return secrets.token_urlsafe(12)


@dataclass
class Session:
    session_id: str
    user_id: str
    family_id: str
    device_hash: str
    device_label: str
    created_at: float
    last_seen: float
    absolute_expires_at: float
    revoked_at: float | None = None

    def active(self) -> bool:
        return self.revoked_at is None


class SessionRevoked(Exception):
    """The session behind this token is revoked, idle or past its absolute end."""


def idle_seconds() -> float:
    return settings.auth_session_idle_days * 86400


def absolute_seconds() -> float:
    return settings.auth_session_absolute_days * 86400


TOUCH_INTERVAL_SECONDS = 60


def create(store, *, user_id: str, device_id: str | None, device_label: str = "",
           now: float | None = None) -> Session:
    now = now or time.time()
    session = Session(
        session_id=new_session_id(),
        user_id=user_id,
        family_id=new_family_id(),
        device_hash=device_hash(device_id or "unknown-device"),
        device_label=(device_label or "unknown device")[:60],
        created_at=now,
        last_seen=now,
        absolute_expires_at=now + absolute_seconds(),
    )
    store.create_session(session)
    return session


def enforce(store, *, user_id: str, device_id: str | None, now: float | None = None) -> Session:
    """Raise SessionRevoked unless an active session exists for this device."""
    now = now or time.time()
    session = store.session_for_device(user_id, device_hash(device_id or "unknown-device"))
    if session is None or not session.active():
        raise SessionRevoked("no active session for this device")
    if now - session.last_seen > idle_seconds():
        store.revoke_session(session.session_id, now)
        raise SessionRevoked("session idle")
    if now > session.absolute_expires_at:
        store.revoke_session(session.session_id, now)
        raise SessionRevoked("session too old")
    if now - session.last_seen > TOUCH_INTERVAL_SECONDS:
        store.touch_session(session.session_id, now)
    return session


def revoke_all(store, user_id: str, now: float | None = None) -> int:
    return store.revoke_all_sessions(user_id, now or time.time())


def revoke_one(store, *, user_id: str, session_id: str, now: float | None = None) -> bool:
    session = store.session_by_id(session_id)
    if session is None or session.user_id != user_id:
        return False
    store.revoke_session(session_id, now or time.time())
    return True


def active_sessions(store, user_id: str) -> list[Session]:
    return [s for s in store.list_sessions(user_id) if s.active()]
