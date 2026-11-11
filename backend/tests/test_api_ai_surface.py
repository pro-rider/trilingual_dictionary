"""HTTP-surface regression tests for the four AI-spending routes.

Written after an audit found two defects that a fully green suite could not see:

* ``GET /api/v1/providers`` raised ``KeyError`` -> HTTP 500, because the view
  still read the legacy ``FailoverLLMService`` stats keys while the strict
  free-only router emitted a different payload;
* ``POST /api/v1/search/sentence`` declared no ``require_ai_access`` /
  ``enforce_limits`` dependency, so a client could spend the free provider
  quota without the shared token.

Every test here runs with AI generation disabled (``tests/conftest.py``), so no
provider is contacted and no quota is spent outside this process.
"""

import pytest
from fastapi.testclient import TestClient

from app.ai.quota import QuotaTracker
from app.core import ai_guard
from app.core.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_limiter():
    """The limiter is process-global; reset it so order cannot change results."""
    ai_guard.limiter.reset()
    yield
    ai_guard.limiter.reset()


# --------------------------------------------------------------- monitoring


def test_providers_returns_the_current_router_stats():
    r = client.get("/api/v1/providers")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema"] == "providers.v2"
    # Keys that come straight from FreeOnlyRouter.stats(); their absence was
    # the cause of the 500 and is what this test pins.
    for key in ("registry", "counters", "breakers", "pools", "free_only",
                "winner", "exhausted", "attempts"):
        assert key in body, key
    assert isinstance(body["active"], list)
    assert body["all_down"] is (not body["active"])


def test_providers_never_echoes_secret_material():
    r = client.get("/api/v1/providers")
    assert "api_key" not in r.text.lower()
    assert "sk-" not in r.text and "gsk_" not in r.text


def test_providers_health_snapshot_is_secretless_and_makes_no_call():
    r = client.get("/api/v1/providers/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema"] == "providers.health.v1"
    assert {"registry", "breakers", "pools", "endpoints", "counters"} <= set(body)
    assert "sk-" not in r.text and "gsk_" not in r.text


# -------------------------------------------------------------------- guards

_AI_ROUTES = [
    ("/api/v1/search", {"q": "light", "lang": "en"}),
    ("/api/v1/analyze/text", {"text": "你好", "lang": "zh"}),
    ("/api/v1/dictionary/enrich", {"items": [{"key": "k1", "zh": "光", "en": "light"}]}),
    ("/api/v1/search/sentence", {"sense_id": "", "word": "zzznotaword"}),
]


@pytest.mark.parametrize("path,payload", _AI_ROUTES)
def test_every_ai_route_requires_the_shared_secret(path, payload, monkeypatch):
    monkeypatch.setenv("AI_SHARED_SECRET", "test-secret")
    assert client.post(path, json=payload).status_code == 401
    assert client.post(path, json=payload,
                       headers={"X-AI-Token": "wrong"}).status_code == 401
    # The valid token must still reach the handler. AI is disabled in tests, so
    # each route answers from dataset/cache/fallback without a provider call.
    assert client.post(path, json=payload,
                       headers={"X-AI-Token": "test-secret"}).status_code == 200


def test_sentence_route_keeps_working_when_no_secret_is_configured():
    """No secret configured = the pre-guard behaviour, which the app relies on."""
    assert client.post("/api/v1/search/sentence",
                       json={"sense_id": "", "word": "zzznotaword"}).status_code == 200


# ------------------------------------------------------------------- limiter


def test_limits_apply_to_a_spending_route_when_ai_is_enabled(monkeypatch):
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setenv("AI_RATE_LIMIT_PER_MIN", "2")
    headers = {"X-Client-Id": "regression-client"}
    codes = [
        client.post("/api/v1/search/sentence",
                    json={"sense_id": "", "word": "light"},
                    headers=headers).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_limiter_counts_guarded_routes_even_with_ai_off(monkeypatch):
    """The limit lives at the boundary, not at the spend site.

    Two independent reasons: the guarded routes can reach a provider as soon as
    AI is switched on mid-run, and a limiter that only works while AI is on
    cannot be reasoned about during an incident.
    """
    monkeypatch.setattr(settings, "ai_enabled", False)
    monkeypatch.setenv("AI_RATE_LIMIT_PER_MIN", "1")
    assert client.post("/api/v1/search",
                       json={"q": "light", "lang": "en"}).status_code == 200
    assert client.post("/api/v1/search",
                       json={"q": "light", "lang": "en"}).status_code == 429


def test_limiter_defaults_are_non_zero():
    """A production deployment must be limited without extra configuration."""
    assert settings.ai_rate_limit_per_min > 0
    assert settings.ai_daily_cap > 0


# -------------------------------------------------------------------- quota


def test_quota_usage_is_persisted_on_every_accepted_request(tmp_path):
    state = tmp_path / "quota.json"
    tracker = QuotaTracker(state_file=state, default_rpm=100, default_rpd=100)
    assert tracker.acquire("pool-a") is True
    assert state.exists(), "acquire() must persist, not only record exhaustion"
    assert tracker.snapshot()["pool-a"]["requests_today"] == 1


def test_quota_usage_survives_a_restart(tmp_path):
    state = tmp_path / "quota.json"
    first = QuotaTracker(state_file=state, default_rpm=100, default_rpd=100)
    assert first.acquire("pool-a") is True
    assert first.acquire("pool-a") is True
    restarted = QuotaTracker(state_file=state, default_rpm=100, default_rpd=100)
    assert restarted.snapshot()["pool-a"]["requests_today"] == 2
    assert restarted.acquire("pool-a") is True
    assert restarted.snapshot()["pool-a"]["requests_today"] == 3


def test_quota_daily_cap_still_blocks_after_restart(tmp_path):
    """The cap is what the persistence protects: a restart must not reset it."""
    state = tmp_path / "quota.json"
    first = QuotaTracker(state_file=state, default_rpm=100, default_rpd=2)
    assert first.acquire("p") is True
    assert first.acquire("p") is True
    assert first.acquire("p") is False
    restarted = QuotaTracker(state_file=state, default_rpm=100, default_rpd=2)
    assert restarted.acquire("p") is False


def test_corrupt_quota_state_fails_open_conservatively(tmp_path):
    """Unreadable state must not crash; it restarts the counter (documented)."""
    state = tmp_path / "quota.json"
    state.write_text("{not json", encoding="utf-8")
    tracker = QuotaTracker(state_file=state, default_rpm=10, default_rpd=10)
    assert tracker.acquire("p") is True
