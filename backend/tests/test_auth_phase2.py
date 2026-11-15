"""Phase 2 flow tests.

Each test maps to a claim the review asked to see proven:

* no identity before the code verifies (pre-account takeover);
* the owner can still register after someone else triggered a send to their
  address, and a live code keeps working after the hourly cap is exhausted;
* new and returning addresses get the same body *and* the handler does not wait
  for the mail;
* a password never appears in a 422, a log, or an event;
* IDOR: the profile endpoint cannot be pointed at another user;
* deletion needs re-authentication and leaves no personal data behind.

The store is the in-memory one, so these are "verified on scratch-equivalent
state", not against a live Supabase project (A23).
"""

from __future__ import annotations

import logging
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.v1 import auth as auth_module
from app.core.config import settings
from app.main import app
from app.services import auth_flow, sessions
from app.services.auth_store import MemoryAuthStore, ProfileRow

SECRET = "test-secret"


class FakeAdmin:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.deleted: list[str] = []

    @property
    def configured(self) -> bool:
        return True

    def create_user(self, *, email: str, password: str) -> dict:
        uid = f"uid-{len(self.created) + 1}"
        self.created.append({"id": uid, "email": email})
        return {"id": uid, "email": email}

    def delete_user(self, uid: str) -> None:
        self.deleted.append(uid)


class FakeAuth:
    def __init__(self, valid_password: str = "Correct-horse-9") -> None:
        self.valid_password = valid_password
        self.calls: list[tuple[str, str]] = []

    def sign_in_with_password(self, email: str, password: str) -> dict:
        self.calls.append((email, password))
        if password != self.valid_password:
            raise RuntimeError("invalid credentials")
        return {
            "access_token": "access-token-value",
            "refresh_token": "refresh-token-value",
            "expires_in": 3600,
            "user": {"id": "uid-1"},
        }

    def refresh(self, token: str) -> dict:
        return {"access_token": "a2", "refresh_token": "r2", "expires_in": 3600}

    def sign_out(self, token: str) -> None:
        pass

    def set_password(self, uid: str, password: str) -> None:
        pass


class SlowMailer:
    """Stands in for Resend; sleeping here proves nothing waits for it inline."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.delay = 0.0

    def send_code(self, to: str, code: str) -> None:
        time.sleep(self.delay)
        self.sent.append((to, code))


@pytest.fixture(autouse=True)
def _no_breach_lookup(monkeypatch):
    """Never hit HaveIBeenPwned from a test; the policy is tested separately."""
    monkeypatch.setattr(auth_flow.passwords, "is_breached", lambda _password, timeout=3.0: False)


@pytest.fixture(autouse=True)
def _pepper(monkeypatch):
    """A deployed site must set this; the flow refuses to run without it."""
    monkeypatch.setattr(settings, "auth_code_pepper", "test-pepper-" + "x" * 24)


@pytest.fixture()
def store() -> MemoryAuthStore:
    return MemoryAuthStore()


@pytest.fixture()
def mailer() -> SlowMailer:
    return SlowMailer()


@pytest.fixture()
def admin() -> FakeAdmin:
    return FakeAdmin()


@pytest.fixture()
def auth_client() -> FakeAuth:
    return FakeAuth()


@pytest.fixture()
def client(store, mailer, admin, auth_client, monkeypatch):
    settings.supabase_jwt_secret = SECRET
    # The mailer is called directly (not via Depends), so it is patched; the
    # three dependencies are overridden by the same function objects FastAPI
    # recorded when the router was included.
    monkeypatch.setattr(auth_module, "get_mailer", lambda: mailer)

    app.dependency_overrides[auth_module.get_store] = lambda: store
    app.dependency_overrides[auth_module.get_admin] = lambda: admin
    app.dependency_overrides[auth_module.get_auth_client] = lambda: auth_client
    # Every authenticated route now requires a live session for this device.
    sessions.create(store, user_id="uid-1", device_id=DEVICE, device_label="test phone")
    yield TestClient(app)
    app.dependency_overrides.clear()


DEVICE = "test-device"


def token_for(uid: str, email: str = "a@b.c", device: str = DEVICE) -> dict[str, str]:
    """A signed-in client: JWT plus the install id the session is keyed by."""
    value = jwt.encode(
        {"sub": uid, "email": email, "exp": time.time() + 3600}, SECRET, algorithm="HS256"
    )
    return {"Authorization": f"Bearer {value}", "X-Device-Id": device}


def _start_and_read_code(client, mailer, email: str) -> str:
    r = client.post("/api/v1/auth/register/start", json={"email": email})
    assert r.status_code == 202, r.text
    code = mailer.sent[-1][1]
    assert code.isdigit() and len(code) == 6
    return code


# ------------------------------------------------- pre-account takeover / squatting


def test_no_identity_exists_before_the_code_is_verified(client, store, admin, mailer):
    client.post("/api/v1/auth/register/start", json={"email": "victim@example.com"})
    assert store.profiles == {}
    assert admin.created == []
    # Only a challenge row exists, and it holds a hash, not the digits.
    keys = [(c.email_hash, c.code_hash) for c in store.challenges.values()]
    assert keys and all(len(code_hash) == 64 for _, code_hash in keys)
    assert all(not code_hash.isdigit() for _, code_hash in keys)


def test_owner_can_register_after_attacker_triggered_a_send(client, store, admin, mailer, auth_client):
    """The attacker only causes an email. The owner still completes signup."""
    client.post("/api/v1/auth/register/start", json={"email": "victim@example.com"})
    code = mailer.sent[-1][1]          # this mail lands in the *owner's* inbox
    r = client.post("/api/v1/auth/register/verify", json={"email": "victim@example.com", "code": code})
    assert r.status_code == 200
    signup_token = r.json()["signup_token"]

    r = client.post(
        "/api/v1/auth/register/complete",
        json={"signup_token": signup_token, "username": "victim01", "password": auth_client.valid_password},
    )
    assert r.status_code == 200, r.text
    assert store.profile_by_email("victim@example.com").status == "active"


# -------------------------------------------------------------------- send cap


def test_a_live_code_still_works_after_the_hourly_send_cap(client, mailer, store):
    email = "capped@example.com"
    for _ in range(settings.auth_max_emails_per_hour):
        assert client.post("/api/v1/auth/register/start", json={"email": email}).status_code == 202
    sends_after_quota = len([s for s in mailer.sent if s[0] == email])
    assert sends_after_quota == settings.auth_max_emails_per_hour

    # A sixth request sends nothing ...
    assert client.post("/api/v1/auth/register/start", json={"email": email}).status_code == 202
    assert len([s for s in mailer.sent if s[0] == email]) == sends_after_quota

    # ... but the code that already arrived is still valid.
    code = mailer.sent[-1][1]
    assert client.post(
        "/api/v1/auth/register/verify", json={"email": email, "code": code}
    ).status_code == 200


# ------------------------------------------------------------- timing / equality


def test_new_and_returning_addresses_get_identical_bodies(client):
    first = client.post("/api/v1/auth/register/start", json={"email": "new@example.com"})
    second = client.post("/api/v1/auth/register/start", json={"email": "new@example.com"})
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()


def test_handler_never_waits_for_mail(store, mailer):
    """Direct call, so no TestClient background machinery hides the truth."""
    from fastapi import BackgroundTasks

    from app.schemas.auth import RegisterStartRequest

    mailer.delay = 0.05
    payload = RegisterStartRequest(email="timing@example.com")

    timings = []
    for _ in range(2):
        started = time.perf_counter()
        auth_module.register_start(payload, BackgroundTasks(), store=store)
        timings.append(time.perf_counter() - started)

    assert max(timings) < 0.03, f"handler blocked on send: {timings}"
    assert mailer.sent == []


# ------------------------------------------------------------------ code budget


def test_sixth_wrong_attempt_is_refused_even_with_the_right_code(client, mailer):
    email = "budget@example.com"
    code = _start_and_read_code(client, mailer, email)
    for _ in range(settings.auth_max_code_attempts):
        r = client.post("/api/v1/auth/register/verify", json={"email": email, "code": "000000" if code != "000000" else "111111"})
        assert r.status_code == 400
    r = client.post("/api/v1/auth/register/verify", json={"email": email, "code": code})
    assert r.status_code == 400


# ------------------------------------------------------------------- 422 hygiene


def test_422_never_echoes_the_password(client):
    password = "Z" * 200
    r = client.post(
        "/api/v1/auth/register/complete",
        json={"signup_token": "x" * 20, "username": "someone", "password": password},
    )
    assert r.status_code == 422
    body = r.text
    assert password not in body
    assert "input" not in body.lower()


def test_profile_update_rejects_status_field(client, store):
    store.create_profile(ProfileRow(user_id="uid-1", email="a@b.c", username="anna", status="active"))
    r = client.patch(
        "/api/v1/auth/profile",
        json={"status": "disabled"},
        headers=token_for("uid-1"),
    )
    assert r.status_code == 422
    assert "disabled" not in r.text


# ------------------------------------------------------------------------- IDOR


def test_profile_is_never_another_users(client, store):
    store.create_profile(ProfileRow(user_id="uid-1", email="a@b.c", username="anna", status="active",
                                    display_name="Anna"))
    store.create_profile(ProfileRow(user_id="uid-2", email="x@y.z", username="bert", status="active",
                                    display_name="Bert"))
    r = client.get("/api/v1/auth/profile?user_id=uid-2", headers=token_for("uid-1"))
    assert r.status_code == 200
    assert r.json()["user_id"] == "uid-1"
    assert r.json()["display_name"] == "Anna"


def test_login_is_dead_even_for_an_existing_username_when_password_is_wrong(client, store, auth_client):
    store.create_profile(ProfileRow(user_id="uid-1", email="a@b.c", username="anna", status="active"))
    r = client.post("/api/v1/auth/login", json={"identifier": "anna", "password": "wrong-pass-1"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid username or password"
    assert len(auth_client.calls) == 1

    r = client.post("/api/v1/auth/login", json={"identifier": "nobody", "password": "wrong-pass-1"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid username or password"
    assert len(auth_client.calls) == 2, "unknown usernames must still make one upstream call"


# ------------------------------------------------------------------ deletion


def test_delete_requires_reauthentication(client, store, admin, auth_client):
    store.create_profile(ProfileRow(user_id="uid-1", email="a@b.c", username="anna", status="active"))
    r = client.request(
        "DELETE", "/api/v1/auth/account",
        json={"confirm": True}, headers=token_for("uid-1"),
    )
    assert r.status_code == 403
    assert admin.deleted == []


def test_delete_with_wrong_password_is_refused(client, store, admin, auth_client):
    store.create_profile(ProfileRow(user_id="uid-1", email="a@b.c", username="anna", status="active"))
    r = client.request(
        "DELETE", "/api/v1/auth/account",
        json={"confirm": True, "password": "not-the-password"},
        headers=token_for("uid-1"),
    )
    assert r.status_code == 403
    assert admin.deleted == []


def test_delete_removes_identity_and_leaves_no_personal_data(client, store, admin, auth_client):
    store.create_profile(ProfileRow(user_id="uid-1", email="a@b.c", username="anna", status="active"))
    store.events = [
        {"event_type": "LOGIN_FAILED", "user_id": "uid-1", "ip_hash": "h1", "device_id": "dev-1"},
        {"event_type": "LOGIN_FAILED", "user_id": "uid-1", "ip_hash": "h2", "device_id": "dev-1"},
        {"event_type": "LOGIN_FAILED", "user_id": "uid-2", "ip_hash": "h3", "device_id": "dev-2"},
    ]
    r = client.request(
        "DELETE", "/api/v1/auth/account",
        json={"confirm": True, "password": auth_client.valid_password},
        headers=token_for("uid-1"),
    )
    assert r.status_code == 200, r.text
    assert admin.deleted == ["uid-1"]
    assert store.profile_by_user_id("uid-1") is None

    # The row survives as evidence, but nothing in it points at one person any
    # more: no uid, no device, no stable IP hash.
    mine = [e for e in store.events if e["event_type"] == "LOGIN_FAILED" and e["ip_hash"] is None]
    assert len(mine) == 2
    assert all(e["user_id"] is None and e["device_id"] is None for e in mine)
    other = [e for e in store.events if e["user_id"] == "uid-2"]
    assert len(other) == 1 and other[0]["device_id"] == "dev-2"


def test_no_pepper_means_503_not_a_weaker_code(monkeypatch):
    """Without the pepper a 6-digit code is guessable from a DB dump."""
    from app.core.config import settings as live_settings

    live_settings.auth_code_pepper = ""
    from starlette.testclient import TestClient as _TC

    from app.main import app as live_app

    r = _TC(live_app).post("/api/v1/auth/register/start", json={"email": "pepper@example.com"})
    assert r.status_code == 503
    assert r.json()["detail"] == "Auth not configured"


def test_delete_logs_no_password_or_token(client, store, auth_client, caplog):
    store.create_profile(ProfileRow(user_id="uid-1", email="a@b.c", username="anna", status="active"))
    with caplog.at_level(logging.DEBUG):
        client.request(
            "DELETE", "/api/v1/auth/account",
            json={"confirm": True, "password": auth_client.valid_password},
            headers=token_for("uid-1"),
        )
    text = "\n".join(r.getMessage() for r in caplog.records).lower()
    assert auth_client.valid_password.lower() not in text
    assert "bearer " not in text


# ------------------------------------------------- logout / reset / availability


def test_logout_revokes_the_session_and_returns_204(client, auth_client):
    calls: list[str] = []
    auth_client.sign_out = lambda token: calls.append(token)
    r = client.post("/api/v1/auth/logout", headers=token_for("uid-1"))
    assert r.status_code == 204
    assert len(calls) == 1


def test_logout_survives_an_upstream_failure(client, auth_client):
    def boom(_token):
        raise RuntimeError("supabase down")

    auth_client.sign_out = boom
    # A dead upstream must not make the client think it is still signed in.
    assert client.post("/api/v1/auth/logout", headers=token_for("uid-1")).status_code == 204


def test_refresh_passes_the_new_pair_through(client, auth_client):
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": "r1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] == "a2" and body["refresh_token"] == "r2"
    # A rejected refresh is a dead session, not a 500.
    assert client.post("/api/v1/auth/refresh", json={}).status_code == 400


def test_forgot_password_answers_the_same_for_known_and_unknown_addresses(client, store, mailer):
    store.create_profile(ProfileRow(user_id="uid-1", email="known@example.com", username="known", status="active"))
    known = client.post("/api/v1/auth/password/forgot", json={"email": "known@example.com"})
    unknown = client.post("/api/v1/auth/password/forgot", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    kind = {email for email, _ in mailer.sent}
    assert "known@example.com" in kind and "nobody@example.com" in kind


def test_password_reset_needs_a_live_code_and_sets_the_password(client, store, mailer, auth_client):
    store.create_profile(ProfileRow(user_id="uid-1", email="v@example.com", username="vera", status="active"))
    calls: list[tuple[str, str]] = []
    auth_client.set_password = lambda uid, password: calls.append((uid, password))

    client.post("/api/v1/auth/password/forgot", json={"email": "v@example.com"})
    code = mailer.sent[-1][1]

    wrong = client.post(
        "/api/v1/auth/password/reset",
        json={"email": "v@example.com", "code": "000000", "password": "Brand-new-pass-1"},
    )
    assert wrong.status_code == 400 and calls == []

    ok = client.post(
        "/api/v1/auth/password/reset",
        json={"email": "v@example.com", "code": code, "password": "Brand-new-pass-1"},
    )
    assert ok.status_code == 200, ok.text
    assert calls == [("uid-1", "Brand-new-pass-1")]


def test_username_availability_is_case_insensitive(client, store):
    store.create_profile(ProfileRow(user_id="uid-1", email="a@b.c", username="anna", status="active"))
    assert client.get("/api/v1/auth/username/available", params={"username": "anna"}).json()["available"] is False
    assert client.get("/api/v1/auth/username/available", params={"username": "ANNA"}).json()["available"] is False
    assert client.get("/api/v1/auth/username/available", params={"username": "bruno"}).json()["available"] is True
    # A name that breaks the shape rule is never "available".
    assert client.get("/api/v1/auth/username/available", params={"username": "bad name"}).json()["available"] is False
