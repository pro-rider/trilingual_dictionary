"""Unit tests for the multi-provider LLM failover service (no network)."""

from __future__ import annotations

from app.ai.base import LLMProvider, ProviderRateLimit
from app.ai.failover import FailoverLLMService


class FakeProvider(LLMProvider):
    """Configurable fake: always succeed, always fail, or fail N times."""

    def __init__(
        self,
        name: str,
        *,
        reply: str = '{"ok": true}',
        fails: int = 0,
        rate_limits: int = 0,
    ) -> None:
        super().__init__(
            name=name, api_key="k", model="m", timeout=5, enabled=True
        )
        self.reply = reply
        self.fails = fails
        self.rate_limits = rate_limits
        self.calls = 0

    def complete(self, system_prompt: str) -> str | None:
        self.calls += 1
        if self.rate_limits > 0:
            self.rate_limits -= 1
            raise ProviderRateLimit(f"{self.name} 429")
        if self.fails > 0:
            self.fails -= 1
            return None
        return self.reply


def _service(providers: list[FakeProvider], **kw) -> FailoverLLMService:
    order = [p.name for p in providers]
    defaults = dict(
        max_retries=1,
        retry_backoff=0.0,
        fail_threshold=3,
        cooldown_seconds=60,
    )
    defaults.update(kw)
    return FailoverLLMService(providers, order, **defaults)


def test_first_provider_wins():
    a, b = FakeProvider("a"), FakeProvider("b")
    s = _service([a, b])
    text, winner, _ = s.complete("hello")
    assert text == '{"ok": true}'
    assert winner == "a"
    assert a.calls == 1
    assert b.calls == 0


def test_fallback_to_next_on_failure():
    a = FakeProvider("a", fails=99)
    b = FakeProvider("b")
    s = _service([a, b])
    text, winner, _ = s.complete("hello")
    assert text is not None
    assert winner == "b"


def test_rate_limit_skips_immediately_to_next():
    a = FakeProvider("a", rate_limits=1)
    b = FakeProvider("b")
    s = _service([a, b])
    text, winner, _ = s.complete("hello")
    assert winner == "b"
    assert a.calls == 1  # 429 → no retry on 'a'


def test_retries_within_provider_then_falls_through():
    a = FakeProvider("a", fails=1)  # first attempt fails, retry succeeds
    b = FakeProvider("b")
    s = _service([a, b], max_retries=1)
    text, winner, _ = s.complete("hello")
    assert winner == "a"
    assert a.calls == 2  # initial + 1 retry


def test_circuit_breaker_opens_and_skips_failing_provider():
    a = FakeProvider("a", fails=99)
    b = FakeProvider("b")
    s = _service([a, b], fail_threshold=2, max_retries=0)
    # Two calls push 'a' to the threshold → circuit opens.
    for _ in range(2):
        _, winner, _ = s.complete("hello")
        assert winner == "b"
    # Now 'a' should be skipped entirely (circuit open), even if it would work.
    s.circuits["a"].open_until = 10**10  # force open
    a.fails = 0
    _, winner, _ = s.complete("hello")
    assert winner == "b"
    assert a.calls == 2  # unchanged after opening


def test_all_down_returns_none_and_graceful():
    a = FakeProvider("a", fails=99)
    b = FakeProvider("b", fails=99)
    s = _service([a, b])
    text, winner, stats = s.complete("hello")
    assert text is None
    assert winner == "none"
    assert stats["active"] == ["a", "b"]
    assert stats["providers"]["a"]["failure_count"] >= 1


def test_disabled_provider_is_skipped():
    a = FakeProvider("a", fails=99)
    a.enabled = False
    b = FakeProvider("b")
    s = _service([a, b])
    _, winner, _ = s.complete("hello")
    assert winner == "b"
    assert a.calls == 0


def test_metrics_track_success_and_latency():
    a = FakeProvider("a", fails=1)
    s = _service([a], max_retries=1)
    s.complete("hello")
    st = s.stats()["providers"]["a"]
    assert st["success_count"] == 1
    assert st["failure_count"] == 0  # retry recovered → not a provider failure
    assert st["avg_latency_ms"] >= 0
