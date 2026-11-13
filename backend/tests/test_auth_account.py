"""Account deletion, cross-user isolation and profile column limits.

The Interesting parts here are the ones a passing HTTP status would hide:

* the endpoint must target the uid **from the JWT**, never a uid the caller
  supplies somewhere else;
* deleting twice must succeed;
* an upstream failure must not leak the address or the token into a log line;
* profile writes must reject identity and lifecycle columns.
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
from app.services import profiles
from app.services.supabase_admin import SupabaseAdminError, SupabaseUserNotFound

client = TestClient(app)
SECRET = "test-secret"


@pytest.fixture()
def token() -> str:
    settings.supabase_jwt_secret = SECRET
    return jwt.encode(
        {"sub": "user-123", "email": "a@b.c", "exp": time.time() + 3600},
        SECRET,
        algorithm="HS256",
    )


class FakeAdmin:
    def __init__(self, outcome: str = "ok") -> None:
        self.outcome = outcome
        self.deleted: list[str] = []

    @property
    def configured(self) -> bool:
        return True

    def delete_user(self, uid: str) -> None:
        if self.outcome == "missing":
            raise SupabaseUserNotFound(uid)
        if self.outcome == "error":
            raise SupabaseAdminError("delete_user failed with HTTP 500")
        self.deleted.append(uid)


@pytest.fixture()
def fake_admin(monkeypatch):
    fake = FakeAdmin()
    monkeypatch.setattr(auth_module, "SupabaseAdmin", lambda: fake)
    return fake


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_delete_requires_confirmation(token, fake_admin):
    r = client.request(
        "DELETE", "/api/v1/auth/account", json={"confirm": False}, headers=_headers(token)
    )
    assert r.status_code == 400
    assert fake_admin.deleted == []


def test_delete_requires_a_valid_token(fake_admin):
    settings.supabase_jwt_secret = SECRET
    r = client.request(
        "DELETE", "/api/v1/auth/account", json={"confirm": True}, headers={"Authorization": "Bearer nope"}
    )
    assert r.status_code == 401
    assert fake_admin.deleted == []


def test_delete_uses_the_jwt_uid_not_a_caller_supplied_one(token, fake_admin):
    """A uid in the query string must be ignored: only the token decides."""
    r = client.request(
        "DELETE",
        "/api/v1/auth/account?uid=someone-else",
        json={"confirm": True},
        headers=_headers(token),
    )
    assert r.status_code == 200
    assert fake_admin.deleted == ["user-123"]


def test_delete_twice_is_a_success(token, monkeypatch):
    monkeypatch.setattr(auth_module, "SupabaseAdmin", lambda: FakeAdmin(outcome="missing"))
    r = client.request("DELETE", "/api/v1/auth/account", json={"confirm": True}, headers=_headers(token))
    assert r.status_code == 200
    assert r.json() == {"deleted": True, "already_absent": True}


def test_upstream_failure_is_generic_and_logged_without_secrets(token, monkeypatch, caplog):
    monkeypatch.setattr(auth_module, "SupabaseAdmin", lambda: FakeAdmin(outcome="error"))
    with caplog.at_level(logging.DEBUG):
        r = client.request(
            "DELETE", "/api/v1/auth/account", json={"confirm": True}, headers=_headers(token)
        )
    assert r.status_code == 502
    assert r.json()["detail"] == "Account could not be deleted"
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert token not in text
    assert "password" not in text.lower()


def test_no_token_or_password_in_logs(token, fake_admin, caplog):
    """The delete path logs an event, not a credential."""
    with caplog.at_level(logging.DEBUG):
        r = client.request(
            "DELETE", "/api/v1/auth/account", json={"confirm": True}, headers=_headers(token)
        )
    assert r.status_code == 200
    text = "\n".join(record.getMessage() for record in caplog.records)
    lowered = text.lower()
    for needle in ("password", "bearer ", "verification code"):
        assert needle not in lowered, f"{needle!r} leaked into a log line"
    assert token not in text


def test_delete_without_configuration_is_503(token, monkeypatch):
    class Unconfigured(FakeAdmin):
        @property
        def configured(self) -> bool:
            return False

    monkeypatch.setattr(auth_module, "SupabaseAdmin", lambda: Unconfigured())
    r = client.request("DELETE", "/api/v1/auth/account", json={"confirm": True}, headers=_headers(token))
    assert r.status_code == 503


# ---------------------------------------------------------------- profile rules


@pytest.mark.parametrize("field", ["status", "username", "email", "user_id", "activated_at"])
def test_profile_update_refuses_identity_and_lifecycle_columns(field):
    with pytest.raises(profiles.ProfileWriteRejected) as exc:
        profiles.validate_profile_update({field: "x"})
    assert field in exc.value.columns


def test_profile_update_allows_only_presentation_columns():
    cleaned = profiles.validate_profile_update({"display_name": "  Surendra ", "locale": "ne"})
    assert cleaned == {"display_name": "Surendra", "locale": "ne"}


def test_username_is_normalised_and_shape_checked():
    assert profiles.normalize_username("  Anna ") == "anna"
    assert profiles.username_shape_errors("anna") == []
    assert profiles.username_shape_errors("Ann") != []
    assert profiles.username_shape_errors("an na") != []
    assert profiles.username_shape_errors("") != []


def test_email_is_normalised():
    assert profiles.normalize_email("  A@B.C ") == "a@b.c"
