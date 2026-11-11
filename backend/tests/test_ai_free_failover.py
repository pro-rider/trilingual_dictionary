"""Tests for the strict free-only 20-slot failover system (no network).

Every test injects its own stub caller, so nothing here hits a provider and no
credential is needed. The registry tests assert *counts and policy*, never that
a provider "works" — that would require a real request.
"""

from __future__ import annotations

import httpx

from app.ai.errors import (AuthFailed, InvalidModel, ProviderTimeout,
                           RateLimited, ServerError)
from app.ai.breaker import BreakerBoard
from app.ai.discovery import CatalogResult, zero_priced
from app.ai.free_policy import decide
from app.ai.quota import QuotaTracker
from app.ai.registry import ModelEndpoint, build_registry, registry_summary
from app.ai.router import FreeOnlyRouter, RouterConfig


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def make_ep(slot: int, model: str, *, env: str, price: float | None = 0.0,
            free: bool = True, pool: str = "pool-a", priority: int = 1,
            json_ok: bool = True, disabled: str = "", provider: str = "testprov",
            ) -> ModelEndpoint:
    return ModelEndpoint(
        slot=slot, provider_id=provider, model_id=model,
        endpoint_type="openai_compatible", base_url="https://example.invalid/v1",
        api_key_env=env, priority=priority, free_verified=free,
        verification_source="test", verification_timestamp="2026-11-11",
        input_price=price, output_price=price,
        account_quota_pool=pool, rate_limit_scope="pool", context_limit=None,
        supports_json=json_ok, supports_tools=False, supports_streaming=False,
        supports_vision=False, timeout_seconds=5, cooldown_seconds=60,
        disabled_reason=disabled,
    )


class Stub:
    """Mimics a provider caller: one scripted outcome per call.

    An exhausted script raises, so a test can never accidentally "pass" because
    a later call silently returned a success the test did not intend.
    """

    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        if not self.script:
            raise RuntimeError("stub script exhausted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return str(item)


def build_router(eps, stubs, *, cfg=None, quota=None, breakers=None,
                 monkeypatch=None) -> FreeOnlyRouter:
    for ep in eps:
        if monkeypatch is not None:
            monkeypatch.setenv(ep.api_key_env, "test-key")
    router = FreeOnlyRouter(
        eps, callers={ep.key: stubs[ep.key] for ep in eps if ep.key in stubs},
        config=cfg or RouterConfig(max_attempts=6, max_retries_per_provider=2,
                                   max_total_request_seconds=30),
        quota=quota, breakers=breakers,
        sleeper=lambda seconds: None,
    )
    return router


# --------------------------------------------------------------------- policy
def test_paid_endpoint_is_never_selected(monkeypatch):
    paid = make_ep(1, "paid/model", env="K_PAID", price=0.002, free=False)
    free = make_ep(2, "free/model:free", env="K_FREE", priority=2)
    router = build_router([paid, free], {free.key: Stub(['{"x":1}'])}, monkeypatch=monkeypatch)
    _check(router.active_providers() == [free.key], "paid endpoint must not be active")
    text, winner, _ = router.complete("hi")
    _check(winner == free.key, "winner must be the free endpoint")


def test_unknown_price_is_treated_as_paid():
    ep = make_ep(1, "mystery/model", env="K", price=None)
    d = decide(ep)
    _check(not d.allowed and "pricing unknown" in d.reason, d.reason)


def test_missing_credential_disables_endpoint(monkeypatch):
    monkeypatch.delenv("K_NOKEY", raising=False)
    ep = make_ep(1, "free/model:free", env="K_NOKEY")
    _check(not decide(ep).allowed, "endpoint without a key must not run")


# ------------------------------------------------------------- error handling
def test_rate_limit_cools_the_whole_pool(monkeypatch):
    a = make_ep(1, "a:free", env="K_A", pool="shared", priority=1)
    b = make_ep(2, "b:free", env="K_B", pool="shared", priority=2)
    c = make_ep(3, "c:free", env="K_C", pool="other", priority=3)
    stubs = {a.key: Stub([RateLimited("429", retry_after=60)]),
             b.key: Stub(['{"x":1}']), c.key: Stub(['{"x":1}', '{"x":1}'])}
    router = build_router([a, b, c], stubs, monkeypatch=monkeypatch)
    text, winner, _ = router.complete('{"x":1}')
    _check(winner == c.key, f"shared pool must be skipped, got {winner}")
    _check(stubs[b.key].calls == 0, "same-pool endpoint must not be called")

    # A second request in the same pool window must still skip a and b.
    _, winner2, _ = router.complete('{"x":1}')
    _check(winner2 == c.key, "pool cooldown must persist across requests")


def test_auth_failure_opens_breaker_immediately(monkeypatch):
    a = make_ep(1, "a:free", env="K_A", priority=1)
    b = make_ep(2, "b:free", env="K_B", priority=2)
    router = build_router([a, b], {a.key: Stub([AuthFailed("401")]), b.key: Stub(['{"x":1}'])},
                          monkeypatch=monkeypatch)
    _, winner, _ = router.complete('{"x":1}')
    _check(winner == b.key, "must continue on the next independent endpoint")
    _check(router.breakers.get(a.key).state == "open", "auth must open the breaker")
    _check(router.breakers.get(a.key).consecutive_failures == 1, "no retry on auth")


def test_invalid_model_is_not_retried(monkeypatch):
    a = make_ep(1, "retired:free", env="K_A")
    b = make_ep(2, "b:free", env="K_B", priority=2)
    stubs = {a.key: Stub([InvalidModel("404")]), b.key: Stub(['{"x":1}'])}
    router = build_router([a, b], stubs, monkeypatch=monkeypatch)
    _, winner, _ = router.complete('{"x":1}')
    _check(winner == b.key, "must fail over to b")
    _check(stubs[a.key].calls == 1, "permanent model error must not be retried")


def test_timeout_fails_over_without_burning_retries(monkeypatch):
    a = make_ep(1, "a:free", env="K_A")
    b = make_ep(2, "b:free", env="K_B", priority=2)
    stubs = {a.key: Stub([ProviderTimeout("t")]), b.key: Stub(['{"x":1}'])}
    router = build_router([a, b], stubs, monkeypatch=monkeypatch)
    _, winner, stats = router.complete('{"x":1}')
    _check(winner == b.key, "b must answer")
    kinds = [x["kind"] for x in stats["attempts"]]
    _check("timeout" in kinds, kinds)
    _check(stubs[a.key].calls == 1, "a timeout must not be retried on the same endpoint")


def test_invalid_json_is_rejected(monkeypatch):
    a = make_ep(1, "a:free", env="K_A")
    stubs = {a.key: Stub(["not json at all"] * 3)}
    router = build_router([a], stubs, monkeypatch=monkeypatch)
    text, winner, stats = router.complete("prompt", task="translation")
    _check(text is None and winner == "none", "malformed output must not be returned")
    _check(stats["last_failure_kind"] == "parse", "must be classified as parse")


# --------------------------------------------------------------- scenarios
def test_mixed_failure_scenario_reaches_provider_e(monkeypatch):
    eps = [make_ep(i, f"m{i}:free", env=f"K_{i}", pool=f"p{i}", priority=i)
           for i in range(1, 6)]
    stubs = {
        eps[0].key: Stub([RateLimited("429", retry_after=30)]),
        eps[1].key: Stub([ProviderTimeout("slow"), ServerError("503")]),
        eps[2].key: Stub([ServerError("503")] * 3),
        eps[3].key: Stub([InvalidModel("404")]),
        eps[4].key: Stub(['{"meaning": "ok"}']),
        "paid:meta": Stub([]),
    }
    paid = make_ep(9, "paid:meta", env="K_PAID", price=0.01, free=False)
    stubs[paid.key] = Stub([])
    router = build_router(eps + [paid], stubs, monkeypatch=monkeypatch,
                          cfg=RouterConfig(max_attempts=10, max_retries_per_provider=2,
                                           max_total_request_seconds=30))
    text, winner, stats = router.complete('{"ask":1}')
    _check(winner == eps[4].key and text == '{"meaning": "ok"}', "E must answer")
    _check(stubs[paid.key].calls == 0, "paid endpoint must never be used")
    kinds = {x["kind"] for x in stats["attempts"]}
    _check({"rate_limit", "timeout", "server", "invalid_model"} <= kinds, kinds)


def test_all_exhausted_returns_controlled_failure(monkeypatch):
    eps = [make_ep(i, f"m{i}:free", env=f"K_{i}", pool=f"p{i}") for i in range(1, 4)]
    stubs = {e.key: Stub([RateLimited("429", retry_after=30)] * 3) for e in eps}
    router = build_router(eps, stubs, monkeypatch=monkeypatch)
    text, winner, stats = router.complete('{"ask":1}')
    _check(text is None and winner == "none", "must not fabricate an answer")
    _check(stats["exhausted"] is True, "stats must mark exhaustion")
    _check(stats["attempts"], "must report which endpoints were tried")


def test_attempt_budget_is_bounded(monkeypatch):
    eps = [make_ep(i, f"m{i}:free", env=f"K_{i}", pool=f"p{i}") for i in range(1, 11)]
    stubs = {e.key: Stub([ServerError("503")] * 4) for e in eps}
    router = build_router(eps, stubs, monkeypatch=monkeypatch,
                          cfg=RouterConfig(max_attempts=6, max_retries_per_provider=2,
                                           max_total_request_seconds=30))
    _, winner, stats = router.complete("hi")
    _check(winner == "none", "nothing should succeed")
    _check(len(stats["attempts"]) <= 6, f"attempt cap breached: {len(stats['attempts'])}")


def test_quota_daily_cap_blocks_pool(monkeypatch):
    a = make_ep(1, "a:free", env="K_A", pool="cap")
    quota = QuotaTracker(default_rpm=10, default_rpd=1)
    router = build_router([a], {a.key: Stub(['{"x":1}'])}, monkeypatch=monkeypatch,
                          quota=quota)
    _, first, _ = router.complete('{"x":1}')
    _check(first == a.key, "first request fits")
    _, second, stats = router.complete('{"x":1}')
    _check(second == "none", "second request must be blocked by the daily cap")
    _check(stats["pools"]["cap"]["exhausted_for_seconds"] > 0, "pool must show cooldown")


def test_secret_is_redacted_in_stats(monkeypatch):
    secret = "sk-live-SECRETSECRET1234"
    monkeypatch.setenv("K_A", secret)
    a = make_ep(1, "a:free", env="K_A")
    stub = Stub([AuthFailed(f"bad key {secret}")])
    router = FreeOnlyRouter([a], callers={a.key: stub},
                            config=RouterConfig(max_attempts=4,
                                                max_retries_per_provider=1,
                                                max_total_request_seconds=20),
                            sleeper=lambda seconds: None)
    _, _, stats = router.complete('{"x":1}')
    blob = repr(stats)
    _check(secret not in blob, "credential leaked into stats")
    _check("[REDACTED]" in blob, "expected redaction marker")


# ------------------------------------------------------------------- registry
def test_registry_has_twenty_slots_and_honest_shortfall():
    eps = build_registry(free_models=None)
    _check(len(eps) == 20, f"expected 20 slots, got {len(eps)}")
    _check(len({e.slot for e in eps}) == 20, "slots must be unique")
    _check(len({e.key for e in eps}) == 20, "endpoint keys must be unique")
    summary = registry_summary(eps)
    _check(summary["slots"] == 20, "summary must report 20 slots")
    _check(summary["verified_free"] < 20,
           "unverified providers must not be counted as verified free")


def test_live_catalogue_demotes_missing_models():
    catalog = {"google/gemma-4-26b-a4b-it:free": {"id": "x", "context_length": 8192}}
    eps = build_registry(free_models=catalog, discovery_source="test",
                         discovery_timestamp="2026-11-11")
    by_model = {e.model_id: e for e in eps}
    _check(by_model["google/gemma-4-26b-a4b-it:free"].disabled_reason == "",
           "model present in the live catalogue must stay enabled")
    _check(by_model["liquid/lfm-3-1.7b:free"].disabled_reason != "",
           "retired model must be demoted with a reason")


def test_zero_priced_filter_requires_both_sides():
    records = [
        {"id": "free-ok", "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "free-in-name-only", "pricing": {"prompt": "0", "completion": "0.0001"}},
        {"id": "unknown", "pricing": {}},
    ]
    kept = zero_priced(records)
    _check(list(kept) == ["free-ok"], f"only fully zero-priced models count, got {kept}")


def test_http_status_classification_matches_error_types():
    req = httpx.Request("POST", "https://example.invalid")
    resp429 = httpx.Response(429, request=req, headers={"retry-after": "12"})
    from app.ai.errors import classify
    f = classify(httpx.HTTPStatusError("429", request=req, response=resp429))
    _check(f.kind == "rate_limit" and f.retryable is False, f)
    _check(f.retry_after == 12.0, "retry-after must be parsed")
    resp401 = httpx.Response(401, request=req)
    f2 = classify(httpx.HTTPStatusError("401", request=req, response=resp401))
    _check(f2.kind == "auth" and f2.scope == "endpoint", f2)
    resp503 = httpx.Response(503, request=req)
    f3 = classify(httpx.HTTPStatusError("503", request=req, response=resp503))
    _check(f3.kind == "server" and f3.retryable is True, f3)


def test_health_reports_slots_without_secrets(monkeypatch):
    a = make_ep(1, "a:free", env="K_HEALTH", pool="p")
    router = build_router([a], {a.key: Stub([])}, monkeypatch=monkeypatch)
    health = router.health()
    _check("test-key" not in repr(health), "health output must not embed the key")
    _check(health["registry"]["slots"] == 1, "registry summary must be present")



# ----------------------------------------------------------------- concurrency
def test_quota_acquire_is_atomic_under_concurrency():
    import threading

    quota = QuotaTracker(default_rpm=5, default_rpd=1000)
    results = []
    lock = threading.Lock()

    def worker():
        got = quota.acquire("pool-conc")
        with lock:
            results.append(got)

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    _check(sum(1 for r in results if r) == 5,
           f"exactly 5 of 40 reservations may succeed, got {sum(results)}")


def test_breaker_half_open_admits_exactly_one_probe():
    import threading
    import time as _time

    board = BreakerBoard(fail_threshold=1, cooldown_seconds=0.01)
    board.get("ep").record_failure("boom")
    _time.sleep(1.05)  # every cooldown is floored at 1 s by design
    allowed = []
    lock = threading.Lock()

    def worker():
        got = board.allow("ep")
        with lock:
            allowed.append(got)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    _check(sum(1 for a in allowed if a) == 1,
           f"half-open must admit one probe, admitted {sum(allowed)}")


def test_concurrent_requests_never_exceed_the_pool_quota(monkeypatch):
    import threading

    ep = make_ep(1, "a:free", env="K_CONC", pool="pool-conc2")
    stub = Stub([f'{{"n":{i}}}' for i in range(40)])
    quota = QuotaTracker(default_rpm=3, default_rpd=1000)
    router = build_router([ep], {ep.key: stub}, quota=quota, monkeypatch=monkeypatch,
                          cfg=RouterConfig(max_attempts=2, max_retries_per_provider=1,
                                           max_total_request_seconds=10))
    winners = []
    lock = threading.Lock()

    def worker():
        text, winner, _ = router.complete('{"n":1}')
        with lock:
            winners.append(winner)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    _check(stub.calls <= 3, f"provider calls must stay within rpm=3, got {stub.calls}")
    _check(sum(1 for w in winners if w != "none") <= 3,
           f"at most 3 requests may win, got {sum(1 for w in winners if w != 'none')}")
