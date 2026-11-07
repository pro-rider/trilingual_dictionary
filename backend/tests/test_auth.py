import time

import jwt
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_me_rejects_when_auth_not_configured():
    settings.supabase_jwt_secret = ""
    r = client.get("/api/v1/me")
    assert r.status_code == 503


def test_me_rejects_bad_token():
    settings.supabase_jwt_secret = "test-secret"
    r = client.get(
        "/api/v1/me", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert r.status_code == 401


def test_me_accepts_valid_supabase_token():
    settings.supabase_jwt_secret = "test-secret"
    token = jwt.encode(
        {"sub": "user-123", "email": "a@b.c", "exp": time.time() + 3600},
        "test-secret",
        algorithm="HS256",
    )
    r = client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["uid"] == "user-123"
    assert body["email"] == "a@b.c"
