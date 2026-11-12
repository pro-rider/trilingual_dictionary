"""Phase 6 — the acceptance tests that the earlier suites did not cover.

Covered elsewhere already: success, 403, 402, 429, 503, timeout classification,
cache hit, and the kill-switch flag file. This file adds:

* the paid provider lane (opt-in by environment, never on by accident);
* a per-device budget that is separate from the global budget, so one client
  cannot spend everyone else's AI;
* the IP fallback that keeps anonymous callers from sharing one key;
* the 180 s overall cap actually ending the chain.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.ai.registry import build_registry
from app.ai.router import FreeOnlyRouter, RouterConfig
from app.core import ai_guard
from app.main import app

from .test_ai_free_failover import Stub, build_router, make_ep


@pytest.fixture(autouse=True)
def _clean_limits(monkeypatch):
    for name in ("AI_RATE_LIMIT_PER_MIN", "AI_DAILY_CAP", "AI_DAILY_CAP_PER_CLIENT",
                 "AI_RATE_LIMIT_GLOBAL_PER_MIN", "AI_SHARED_SECRET",
                 "AI_RUNTIME_ENABLED", "AI_ALLOW_PAID", "PAID_PROVIDER_BASE_URL",
                 "PAID_PROVIDER_MODEL", "PAID_PROVIDER_API_KEY_ENV"):
        monkeypatch.delenv(name, raising=False)
    ai_guard.limiter.reset()
    yield
    ai_guard.limiter.reset()


# ---------------------------------------------------------------- paid lane


def test_paid_lane_is_off_by_default():
    eps = build_registry(free_models=None)
    paid = [e for e in eps if e.provider_id == "paid"]
    assert len(paid) == 1
    assert paid[0].active is False
    assert "AI_ALLOW_PAID" in paid[0].disabled_reason

def test_paid_lane_switches_on_from_the_environment(monkeypatch):
    from app.ai.free_policy import decide

    monkeypatch.setenv("AI_ALLOW_PAID", "1")
    monkeypatch.setenv("PAID_PROVIDER_BASE_URL", "https://paid.example.invalid/v1")
    monkeypatch.setenv("PAID_PROVIDER_MODEL", "vendor/model-large")
    monkeypatch.setenv("PAID_PROVIDER_API_KEY_ENV", "MY_PAID_KEY")
    monkeypatch.setenv("MY_PAID_KEY", "secret-value")

    eps = build_registry(free_models=None)
    paid = [e for e in eps if e.provider_id == "paid"][0]
    assert paid.disabled_reason == "", "an explicitly enabled paid lane must not be blocked"
    assert paid.configured is True
    assert paid.api_key_env == "MY_PAID_KEY"
    # Still not "free": under the free-only policy it stays refused, and it is
    # never counted among the zero-cost providers.
    assert paid.free_verified is False
    assert decide(paid, free_only=False).allowed is True
    assert decide(paid, free_only=True).allowed is False


def test_paid_lane_without_a_key_stays_inactive(monkeypatch):
    monkeypatch.setenv("AI_ALLOW_PAID", "1")
    monkeypatch.setenv("PAID_PROVIDER_BASE_URL", "https://paid.example.invalid/v1")
    monkeypatch.setenv("PAID_PROVIDER_MODEL", "vendor/model-large")
    eps = build_registry(free_models=None)
    paid = [e for e in eps if e.provider_id == "paid"][0]
    assert paid.active is False, "a lane with no credential must stay dark"


# ------------------------------------------------------- per-client budgets


def _post(client, text="company", client_id=None):
    headers = {"X-Client-Id": client_id} if client_id else {}
    return client.post("/api/v1/analyze/text",
                       json={"text": text, "lang": "en"}, headers=headers)


def test_one_device_cannot_consume_the_whole_ai_budget(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.ai_enabled", False)
    monkeypatch.setenv("AI_DAILY_CAP_PER_CLIENT", "2")
    monkeypatch.setenv("AI_DAILY_CAP", "1000")
    monkeypatch.setenv("AI_RATE_LIMIT_PER_MIN", "0")
    monkeypatch.setenv("AI_RATE_LIMIT_GLOBAL_PER_MIN", "0")
    client = TestClient(app)

    assert _post(client, client_id="device-A").status_code == 200
    assert _post(client, client_id="device-A").status_code == 200
    blocked = _post(client, client_id="device-A")
    assert blocked.status_code == 429, "the heavy device must be stopped"
    # ...and everybody else keeps working.
    assert _post(client, client_id="device-B").status_code == 200


def test_global_budget_still_protects_the_provider_quota(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.ai_enabled", False)
    monkeypatch.setenv("AI_DAILY_CAP_PER_CLIENT", "1000")
    monkeypatch.setenv("AI_DAILY_CAP", "2")
    monkeypatch.setenv("AI_RATE_LIMIT_PER_MIN", "0")
    monkeypatch.setenv("AI_RATE_LIMIT_GLOBAL_PER_MIN", "0")
    client = TestClient(app)

    assert _post(client, client_id="device-A").status_code == 200
    assert _post(client, client_id="device-B").status_code == 200
    assert _post(client, client_id="device-C").status_code == 429


def test_global_per_minute_ceiling_is_separate_from_the_client_ceiling(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.ai_enabled", False)
    monkeypatch.setenv("AI_RATE_LIMIT_PER_MIN", "10")
    monkeypatch.setenv("AI_RATE_LIMIT_GLOBAL_PER_MIN", "2")
    monkeypatch.setenv("AI_DAILY_CAP", "0")
    monkeypatch.setenv("AI_DAILY_CAP_PER_CLIENT", "0")
    client = TestClient(app)

    assert _post(client, client_id="a").status_code == 200
    assert _post(client, client_id="b").status_code == 200
    assert _post(client, client_id="c").status_code == 429


def test_anonymous_callers_are_keyed_by_ip_not_by_one_shared_word():
    class FakeClient:
        def __init__(self, host):
            self.host = host

    class FakeRequest:
        def __init__(self, host):
            self.client = FakeClient(host)

    assert ai_guard._client_key(FakeRequest("10.0.0.1"), None) == "ip:10.0.0.1"
    assert ai_guard._client_key(FakeRequest("10.0.0.2"), None) == "ip:10.0.0.2"
    assert ai_guard._client_key(FakeRequest("10.0.0.1"), "device-A") == "dev:device-A"


def test_limiter_reports_which_budget_was_hit():
    window = ai_guard._SlidingWindow()
    allowed, _ = window.allow("k", per_minute=0, daily_cap=2, global_per_minute=0,
                              global_daily_cap=10, now=0.0)
    assert allowed
    allowed, _ = window.allow("k", per_minute=0, daily_cap=2, global_per_minute=0,
                              global_daily_cap=10, now=0.1)
    assert allowed
    allowed, reason = window.allow("k", per_minute=0, daily_cap=2, global_per_minute=0,
                                   global_daily_cap=10, now=0.2)
    assert allowed is False and reason == "client_daily_cap"


# --------------------------------------------------------------- overall cap


def test_overall_deadline_stops_the_chain_even_with_healthy_endpoints(monkeypatch):
    """A slow endpoint must not stretch one request past the overall cap."""
    from app.ai.errors import ProviderTimeout

    eps = [make_ep(1, "m1", env="K1", pool="p1", priority=1),
           make_ep(2, "m2", env="K2", pool="p2", priority=2),
           make_ep(3, "m3", env="K3", pool="p3", priority=3)]
    for ep in eps:
        monkeypatch.setenv(ep.api_key_env, "test-key")

    class Slow:
        def __init__(self):
            self.calls = 0

        def complete(self, prompt):
            self.calls += 1
            time.sleep(0.45)
            raise ProviderTimeout("simulated hang")

    stubs = {ep.key: Slow() for ep in eps}
    router = FreeOnlyRouter(
        eps, callers=stubs,
        config=RouterConfig(max_attempts=20, max_retries_per_provider=5,
                            max_total_request_seconds=0.3, validate_json=False),
        sleeper=lambda seconds: None,
    )
    started = time.monotonic()
    text, winner, stats = router.complete("p", task="gloss", require_json=False)
    elapsed = time.monotonic() - started

    assert text is None and winner == "none"
    assert stats["exhausted"] is True
    # Without the cap the chain would spend ~1.35 s on three endpoints.
    assert elapsed < 1.0, f"the 0.3 s cap was ignored: ran {elapsed:.2f}s"
    assert len(stats["attempts"]) == 1, "the second endpoint must not be tried"
