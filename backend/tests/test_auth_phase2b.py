"""Phase 2b: sessions, and the tests the review said Phase 2 lacked.

Everything here runs against the in-memory store — "VERIFIED (fakes)". The
session clocks are asserted by moving timestamps, not by waiting.
"""

from __future__ import annotations

import time

import pytest

from app.services import auth_flow, sessions
from app.services.auth_store import MemoryAuthStore, ProfileRow
from app.services.sessions import SessionRevoked

from tests.test_auth_phase2 import (  # reuse the fixtures built there
    DEVICE,
    FakeAdmin,
    FakeAuth,
    SlowMailer,
    token_for,
)


@pytest.fixture()
def store():
    return MemoryAuthStore()


@pytest.fixture()
def mailer():
    return SlowMailer()


@pytest.fixture()
def admin():
    return FakeAdmin()


@pytest.fixture()
def auth_client():
    return FakeAuth()


@pytest.fixture()
def client(store, mailer, admin, auth_client, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api.v1 import auth as auth_module
    from app.core.config import settings
    from app.main import app

    settings.supabase_jwt_secret = "test-secret"
    settings.auth_code_pepper = "test-pepper-" + "x" * 24
    monkeypatch.setattr(auth_flow.passwords, "is_breached", lambda _p, timeout=3.0: False)
    monkeypatch.setattr(auth_module, "get_mailer", lambda: mailer)
    app.dependency_overrides[auth_module.get_store] = lambda: store
    app.dependency_overrides[auth_module.get_admin] = lambda: admin
    app.dependency_overrides[auth_module.get_auth_client] = lambda: auth_client
    sessions.create(store, user_id="uid-1", device_id=DEVICE, device_label="test phone")
    yield TestClient(app)
    app.dependency_overrides.clear()


def active_profile(store, uid: str = "uid-1", username: str = "anna", email: str = "a@b.c",
                   status: str = "active") -> ProfileRow:
    row = ProfileRow(user_id=uid, email=email, username=username, status=status)
    store.create_profile(row)
    return row


# ------------------------------------------------------------------ session list


def test_session_list_shows_this_device_without_identifiers(client):
    body = client.get("/api/v1/auth/sessions", headers=token_for("uid-1")).json()
    assert len(body["sessions"]) == 1
    entry = body["sessions"][0]
    assert entry["current"] is True
    assert entry["device_label"] == "test phone"
    # No IP, no token, no e-mail in the payload.
    assert set(entry) == {"session_id", "device_label", "created_at", "last_seen", "current"}


def test_logout_all_kills_every_device_immediately(client, store):
    sessions.create(store, user_id="uid-1", device_id="tablet", device_label="tablet")
    assert client.post("/api/v1/auth/logout-all", headers=token_for("uid-1")).status_code == 204
    assert client.get("/api/v1/auth/profile", headers=token_for("uid-1")).status_code == 401
    assert client.get(
        "/api/v1/auth/profile", headers=token_for("uid-1", device="tablet")
    ).status_code == 401


def test_idle_session_is_retired(client, store):
    session = store.session_for_device("uid-1", sessions.device_hash(DEVICE))
    session.last_seen = time.time() - 8 * 86400        # idle limit is 7 days
    assert client.get("/api/v1/auth/profile", headers=token_for("uid-1")).status_code == 401
    assert session.revoked_at is not None


def test_absolute_expiry_retires_an_active_session(client, store):
    session = store.session_for_device("uid-1", sessions.device_hash(DEVICE))
    session.last_seen = time.time() - 60                # recently active
    session.absolute_expires_at = time.time() - 1       # but 31 days old
    assert client.get("/api/v1/auth/profile", headers=token_for("uid-1")).status_code == 401
    assert session.revoked_at is not None


def test_revoking_one_device_leaves_the_other_signed_in(client, store):
    active_profile(store)
    sessions.create(store, user_id="uid-1", device_id="tablet", device_label="tablet")
    tablet_id = store.session_for_device(
        "uid-1", sessions.device_hash("tablet")
    ).session_id

    assert client.delete(
        f"/api/v1/auth/sessions/{tablet_id}", headers=token_for("uid-1")
    ).status_code == 204
    assert client.get(
        "/api/v1/auth/profile", headers=token_for("uid-1", device="tablet")
    ).status_code == 401
    assert client.get("/api/v1/auth/profile", headers=token_for("uid-1")).status_code == 200


def test_a_user_cannot_revoke_someone_elses_session(client, store):
    sessions.create(store, user_id="uid-2", device_id="other", device_label="other")
    other_id = store.session_for_device("uid-2", sessions.device_hash("other")).session_id
    assert client.delete(
        f"/api/v1/auth/sessions/{other_id}", headers=token_for("uid-1")
    ).status_code == 404
    assert store.session_by_id(other_id).revoked_at is None


def test_enforce_rejects_a_device_with_no_session(store):
    with pytest.raises(SessionRevoked):
        sessions.enforce(store, user_id="uid-1", device_id="never-signed-in")


def test_logout_revokes_the_local_row_too(client, store):
    assert client.post("/api/v1/auth/logout", headers=token_for("uid-1")).status_code == 204
    assert client.get("/api/v1/auth/profile", headers=token_for("uid-1")).status_code == 401


# --------------------------------------------------------------- login coverage


def test_login_by_username_and_by_email_both_succeed(client, store):
    active_profile(store)

    by_name = client.post(
        "/api/v1/auth/login",
        json={"identifier": "anna", "password": "Correct-horse-9", "device_id": "phone-a"},
    )
    assert by_name.status_code == 200 and by_name.json()["access_token"] == "access-token-value"
    assert store.session_for_device("uid-1", sessions.device_hash("phone-a")) is not None

    by_email = client.post(
        "/api/v1/auth/login",
        json={"identifier": "A@B.C", "password": "Correct-horse-9", "device_id": "phone-b"},
    )
    assert by_email.status_code == 200


def test_an_unknown_username_still_makes_one_upstream_call(client, auth_client):
    """The dummy-address path: never skip the password grant for unknown users.

    The fake upstream accepts any password, so the fake cannot show the 401 a
    real Supabase would return; what it proves is that exactly one grant is
    attempted, against the placeholder address, so timing does not shorten.
    """
    client.post(
        "/api/v1/auth/login",
        json={"identifier": "nobody-here", "password": "Correct-horse-9"},
    )
    assert auth_client.calls == [("unknown@invalid.local", "Correct-horse-9")]


def test_a_pending_account_cannot_log_in(client, store):
    active_profile(store, status="pending")
    r = client.post(
        "/api/v1/auth/login",
        json={"identifier": "anna", "password": "Correct-horse-9"},
    )
    assert r.status_code == 401
    assert "Invalid username or password" in r.text


# ------------------------------------------------------- register/complete rules


def _signup_token(client, mailer) -> str:
    client.post("/api/v1/auth/register/start", json={"email": "new@example.com"})
    code = mailer.sent[-1][1]
    return client.post(
        "/api/v1/auth/register/verify", json={"email": "new@example.com", "code": code}
    ).json()["signup_token"]


def test_complete_creates_an_active_profile_only_there(client, store, mailer):
    token = _signup_token(client, mailer)
    assert store.profiles == {}                       # nothing before completion
    r = client.post(
        "/api/v1/auth/register/complete",
        json={"signup_token": token, "username": "Newbie", "password": "Correct-horse-9"},
        headers={"X-Device-Id": "fresh-device"},
    )
    assert r.status_code == 200, r.text
    profile = store.profile_by_username("newbie")
    assert profile.status == "active"
    assert profile.nepali_enabled is True
    assert store.session_for_device("uid-1", sessions.device_hash("fresh-device")) is not None


@pytest.mark.parametrize("username", ["admin", "support", "root"])
def test_reserved_usernames_are_refused(client, mailer, username):
    token = _signup_token(client, mailer)
    r = client.post(
        "/api/v1/auth/register/complete",
        json={"signup_token": token, "username": username, "password": "Correct-horse-9"},
    )
    assert r.status_code == 400
    assert "reserved" in r.text.lower()


@pytest.mark.parametrize("username", ["ab", "bad name", "Ünïcode"])
def test_username_policy_is_enforced(client, mailer, username):
    token = _signup_token(client, mailer)
    r = client.post(
        "/api/v1/auth/register/complete",
        json={"signup_token": token, "username": username, "password": "Correct-horse-9"},
    )
    # Too short is caught by the request schema (422); bad characters by policy (400).
    assert r.status_code in (400, 422)


def test_a_password_equal_to_the_username_is_refused(client, mailer):
    token = _signup_token(client, mailer)
    r = client.post(
        "/api/v1/auth/register/complete",
        json={"signup_token": token, "username": "samsam1234", "password": "samsam1234"},
    )
    assert r.status_code == 400
    assert "username" in r.text.lower()


# ------------------------------------------------------------------ nepali_enabled


def test_nepali_enabled_is_visible_and_not_settable_by_patch(client, store):
    active_profile(store)
    body = client.get("/api/v1/auth/profile", headers=token_for("uid-1")).json()
    assert body["nepali_enabled"] is True

    # extra="forbid" + allow-list: the field is not part of the update schema.
    assert client.patch(
        "/api/v1/auth/profile",
        json={"nepali_enabled": False},
        headers=token_for("uid-1"),
    ).status_code == 422


# ------------------------------------------------------- reset revokes the family


def test_password_reset_revokes_every_session(client, store, mailer, auth_client):
    active_profile(store, email="v@example.com", username="vera")
    sessions.create(store, user_id="uid-1", device_id="tablet", device_label="tablet")

    client.post("/api/v1/auth/password/forgot", json={"email": "v@example.com"})
    code = mailer.sent[-1][1]
    r = client.post(
        "/api/v1/auth/password/reset",
        json={"email": "v@example.com", "code": code, "password": "Brand-new-pass-1"},
    )
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/auth/profile", headers=token_for("uid-1")).status_code == 401
    assert client.get(
        "/api/v1/auth/profile", headers=token_for("uid-1", device="tablet")
    ).status_code == 401


# ------------------------------------------------------------ deletion leftovers


def test_deletion_removes_challenges_and_signup_tokens(client, store, mailer, admin, auth_client):
    active_profile(store, email="gone@example.com", username="gone")
    auth_client.valid_password = "Correct-horse-9"
    client.post("/api/v1/auth/password/forgot", json={"email": "gone@example.com"})
    assert store.challenges
    client.post("/api/v1/auth/register/start", json={"email": "gone@example.com"})
    store.signup_tokens["hash-of-something"] = ("gone@example.com", time.time() + 60)

    r = client.request(
        "DELETE", "/api/v1/auth/account",
        json={"confirm": True, "password": "Correct-horse-9"},
        headers=token_for("uid-1"),
    )
    assert r.status_code == 200, r.text
    assert store.challenges == {}
    assert store.signup_tokens == {}


# ------------------------------------------------------- password change revokes


def test_password_change_revokes_every_session(client, store, auth_client):
    active_profile(store, email="pat@example.com", username="pat")
    sessions.create(store, user_id="uid-1", device_id="tablet", device_label="tablet")
    auth_client.valid_password = "Old-password-42"

    r = client.post(
        "/api/v1/auth/password/change",
        json={"current_password": "Old-password-42", "new_password": "New-password-77"},
        headers=token_for("uid-1"),
    )
    assert r.status_code == 204, r.text
    # Both the caller's device and the tablet are out; the app signs in again.
    assert client.get("/api/v1/auth/profile", headers=token_for("uid-1")).status_code == 401
    assert client.get(
        "/api/v1/auth/profile", headers=token_for("uid-1", device="tablet")
    ).status_code == 401


def test_password_change_requires_the_current_password(client, store, auth_client):
    active_profile(store, email="pat@example.com", username="pat")
    sessions.create(store, user_id="uid-1", device_id="tablet", device_label="tablet")
    auth_client.valid_password = "Old-password-42"

    r = client.post(
        "/api/v1/auth/password/change",
        json={"current_password": "not-the-password", "new_password": "New-password-77"},
        headers=token_for("uid-1"),
    )
    assert r.status_code == 403, r.text
    # Nothing was revoked: an attacker with a stolen token cannot end sessions.
    assert client.get("/api/v1/auth/profile", headers=token_for("uid-1")).status_code == 200
    assert client.get(
        "/api/v1/auth/profile", headers=token_for("uid-1", device="tablet")
    ).status_code == 200


def test_password_change_applies_the_password_policy(client, store, auth_client):
    active_profile(store, email="pat@example.com", username="patsmith")
    auth_client.valid_password = "Old-password-42"
    r = client.post(
        "/api/v1/auth/password/change",
        json={"current_password": "Old-password-42", "new_password": "patsmith"},
        headers=token_for("uid-1"),
    )
    assert r.status_code in (400, 422), r.text
    assert client.get("/api/v1/auth/profile", headers=token_for("uid-1")).status_code == 200


# --------------------------------------------------------- disposable domains


def test_register_start_refuses_a_disposable_domain(client, mailer):
    r = client.post("/api/v1/auth/register/start", json={"email": "throwaway@mailinator.com"})
    assert r.status_code == 400
    assert mailer.sent == []                 # no code is spent on it
    assert "permanent email" in r.text.lower()


def test_a_subdomain_of_a_disposable_domain_is_refused(client):
    r = client.post("/api/v1/auth/register/start", json={"email": "a@inbox.mailinator.com"})
    assert r.status_code == 400


def test_allow_override_unblocks_a_false_positive(client, mailer, monkeypatch):
    from app.services import disposable_domains

    disposable_domains.reload()
    monkeypatch.setenv("AUTH_DISPOSABLE_ALLOW_DOMAINS", "mailinator.com")
    r = client.post("/api/v1/auth/register/start", json={"email": "real@mailinator.com"})
    assert r.status_code == 202
    assert mailer.sent and mailer.sent[-1][0] == "real@mailinator.com"
    monkeypatch.delenv("AUTH_DISPOSABLE_ALLOW_DOMAINS")
    disposable_domains.reload()


def test_ordinary_domains_are_not_blocked(client, mailer):
    r = client.post("/api/v1/auth/register/start", json={"email": "someone@gmail.com"})
    assert r.status_code == 202
    assert mailer.sent
