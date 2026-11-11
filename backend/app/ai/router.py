"""Free-only failover router.

Order of gates for every request:

    AI guard (outside this module) → free policy → capability filter
    → endpoint breaker → quota pool → call → validate → record

Guarantees this router enforces, and that tests pin:

* paid endpoints are never selected, even as a last resort;
* one request can never exceed ``max_attempts`` calls or ``total_deadline``;
* 429 cools the whole quota pool (one OpenRouter key = one pool);
* auth / invalid-model failures open the endpoint breaker immediately
  (permanent failures are not retried);
* unknown failures are not retried and never fall back to a paid slot;
* exhaustion returns ``None`` + a diagnosable stats payload — never a
  fabricated answer.
"""

from __future__ import annotations

import json
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field

from app.ai.breaker import BreakerBoard
from app.ai.errors import Failure, ProviderTimeout, classify
from app.ai.free_policy import allowed_candidates, decide
from app.ai.quota import QuotaTracker
from app.ai.redaction import redact, register_secret
from app.ai.registry import ModelEndpoint, registry_summary

logger = logging.getLogger("app.ai.router")

# One shared executor: a hung provider call is abandoned at the deadline instead
# of blocking the request (and the event loop) for minutes. Live evidence:
# one Gemini call ran 209 s despite a 40 s httpx timeout, which silently blew
# the whole request budget.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai-call")

# Tasks whose models must be able to emit JSON without repair.
_JSON_TASKS = {"translation", "dictionary", "verification", "json", "classification"}


@dataclass
class Attempt:
    endpoint: str
    kind: str
    message: str
    latency_ms: float
    attempt_no: int


@dataclass
class RouterConfig:
    free_only: bool = True
    max_attempts: int = 6
    max_retries_per_provider: int = 2
    request_timeout_seconds: float = 45.0
    max_total_request_seconds: float = 180.0
    fail_threshold: int = 3
    cooldown_seconds: float = 60.0
    quota_rpm: int = 20
    quota_rpd: int = 1000
    validate_json: bool = True


class FreeOnlyRouter:
    """Fails over across verified-free endpoints only."""

    def __init__(
        self,
        endpoints: list[ModelEndpoint],
        callers: dict[str, object] | None = None,
        *,
        config: RouterConfig | None = None,
        quota: QuotaTracker | None = None,
        breakers: BreakerBoard | None = None,
        caller_factory=None,
        sleeper=None,
    ) -> None:
        self.cfg = config or RouterConfig()
        self.endpoints = endpoints
        for ep in endpoints:
            register_secret(ep.api_key())
        self._sleep = sleeper or time.sleep
        self.breakers = breakers or BreakerBoard(self.cfg.fail_threshold,
                                                 self.cfg.cooldown_seconds)
        self.quota = quota or QuotaTracker(default_rpm=self.cfg.quota_rpm,
                                           default_rpd=self.cfg.quota_rpd)
        self._factory = caller_factory
        self._callers: dict[str, object] = dict(callers or {})
        self.attempts_total = 0
        self.successes = 0
        self.failures = 0
        self._last_stats: dict = {}

    # ------------------------------------------------------------- helpers
    def _caller(self, ep: ModelEndpoint):
        c = self._callers.get(ep.key)
        if c is None:
            if self._factory is None:
                return None
            c = self._factory(ep)
            self._callers[ep.key] = c
        return c

    def active_providers(self) -> list[str]:
        """Endpoints that pass the free policy *and* have a credential."""
        return [e.key for e in allowed_candidates(self.endpoints,
                                                  free_only=self.cfg.free_only)]

    def _call_with_deadline(self, caller, prompt: str, ep: ModelEndpoint) -> str:
        """Hard per-attempt deadline. A slow socket must not eat the request."""
        budget = float(ep.timeout_seconds) + 1.0
        future = _EXECUTOR.submit(caller.complete, prompt)
        try:
            return future.result(timeout=budget)
        except FutureTimeout as exc:
            future.cancel()
            raise ProviderTimeout(f"{ep.key} exceeded {budget:.0f}s") from exc

    def _eligible(self, require_json: bool, vision: bool) -> list[ModelEndpoint]:
        out = []
        for ep in allowed_candidates(self.endpoints, free_only=self.cfg.free_only):
            if require_json and not ep.supports_json:
                continue
            if vision and not ep.supports_vision:
                continue
            out.append(ep)
        return out

    # ---------------------------------------------------------------- public
    def complete(self, prompt: str, *, task: str = "generic",
                 require_json: bool | None = None
                 ) -> tuple[str | None, str, dict]:
        """Run the chain. Returns ``(text, winner, stats)``."""
        if require_json is None:
            require_json = task in _JSON_TASKS and self.cfg.validate_json
        deadline = time.monotonic() + self.cfg.max_total_request_seconds
        attempts: list[Attempt] = []
        tried_per_endpoint: dict[str, int] = {}
        total = 0
        last_kind = "none"

        for ep in self._eligible(bool(require_json), task == "vision"):
            if total >= self.cfg.max_attempts or time.monotonic() >= deadline:
                break
            if decide(ep, free_only=self.cfg.free_only).allowed is False:
                continue
            if not self.breakers.allow(ep.key) or not self.breakers.allow(ep.account_quota_pool):
                continue
            if not self.quota.allow(ep.account_quota_pool):
                continue

            caller = self._caller(ep)
            if caller is None:
                continue

            for attempt_no in range(1, self.cfg.max_retries_per_provider + 2):
                if total >= self.cfg.max_attempts or time.monotonic() >= deadline:
                    break
                # Reserve the slot atomically: a pre-check alone lets two
                # concurrent requests both see "one left" and both send.
                if not self.quota.acquire(ep.account_quota_pool):
                    break
                total += 1
                self.attempts_total += 1
                start = time.perf_counter()
                try:
                    text = self._call_with_deadline(caller, prompt, ep)
                except Exception as exc:                     # noqa: BLE001
                    latency = (time.perf_counter() - start) * 1000
                    failure: Failure = classify(exc)
                    last_kind = failure.kind
                    attempts.append(Attempt(ep.key, failure.kind,
                                            redact(failure.message), latency, attempt_no))
                    self._record_failure(ep, failure)
                    self.failures += 1
                    logger.warning("ai_attempt endpoint=%s kind=%s attempt=%d latency_ms=%.0f",
                                   ep.key, failure.kind, attempt_no, latency)
                    if not failure.retryable:
                        break
                    # A timeout already burnt the full endpoint budget; retrying
                    # the same black hole is how a 45 s request becomes 200 s.
                    retries = 0 if failure.kind == "timeout" else self.cfg.max_retries_per_provider
                    if attempt_no <= retries:
                        self._sleep(self._backoff(attempt_no, failure.retry_after))
                        continue
                    break

                latency = (time.perf_counter() - start) * 1000
                if require_json and not _is_json(text):
                    failure = Failure("parse", True, "none", "invalid JSON output")
                    last_kind = "parse"
                    attempts.append(Attempt(ep.key, "parse", failure.message, latency, attempt_no))
                    self._record_failure(ep, failure)
                    self.failures += 1
                    if attempt_no <= self.cfg.max_retries_per_provider:
                        self._sleep(self._backoff(attempt_no, None))
                        continue
                    break

                self.breakers.get(ep.key).record_success()
                self.breakers.get(ep.account_quota_pool).record_success()
                self.successes += 1
                attempts.append(Attempt(ep.key, "ok", "", latency, attempt_no))
                logger.info("ai_attempt endpoint=%s kind=ok attempt=%d latency_ms=%.0f",
                            ep.key, attempt_no, latency)
                stats = self.stats(attempts, winner=ep.key, exhausted=False)
                self._last_stats = stats
                return text, ep.key, stats

        stats = self.stats(attempts, winner="none", exhausted=True, last_kind=last_kind)
        self._last_stats = stats
        logger.error("ai_chain_exhausted attempts=%d last_kind=%s", len(attempts), last_kind)
        return None, "none", stats

    # ----------------------------------------------------------- internals
    def _backoff(self, attempt_no: int, retry_after: float | None) -> float:
        if retry_after:
            return min(float(retry_after), 5.0)
        base = min(2.0 ** (attempt_no - 1), 8.0)
        return base + random.uniform(0.0, 0.4)

    def _record_failure(self, ep: ModelEndpoint, failure: Failure) -> None:
        permanent = failure.kind in {"auth", "invalid_model", "free_policy"}
        self.breakers.get(ep.key).record_failure(
            f"{failure.kind}: {redact(failure.message)}", permanent=permanent,
            cooldown=self.cfg.cooldown_seconds if failure.kind != "rate_limit" else 1.0)
        if failure.kind == "rate_limit":
            wait = failure.retry_after or self.cfg.cooldown_seconds
            self.quota.record_quota_exhausted(ep.account_quota_pool, wait,
                                              "provider 429")
            self.breakers.get(ep.account_quota_pool).record_failure(
                "rate limit", cooldown=wait)
        elif failure.kind in {"timeout", "connection", "server"}:
            self.breakers.get(ep.account_quota_pool).record_failure(failure.kind)

    def stats(self, attempts: list[Attempt] | None = None, *, winner: str = "none",
              exhausted: bool = False, last_kind: str = "none") -> dict:
        attempts = attempts or []
        return {
            "winner": winner,
            "exhausted": exhausted,
            "last_failure_kind": last_kind,
            "attempts": [
                {"endpoint": a.endpoint, "kind": a.kind, "attempt": a.attempt_no,
                 "latency_ms": round(a.latency_ms, 1), "message": a.message}
                for a in attempts
            ],
            "registry": registry_summary(self.endpoints),
            "pools": self.quota.snapshot(),
            "breakers": self.breakers.snapshot(),
            "counters": {"attempts": self.attempts_total, "successes": self.successes,
                         "failures": self.failures},
            "free_only": self.cfg.free_only,
        }

    def health(self) -> dict:
        return {
            "registry": registry_summary(self.endpoints),
            "breakers": self.breakers.snapshot(),
            "pools": self.quota.snapshot(),
            "endpoints": [
                {"key": e.key, "slot": e.slot, "active": e.active,
                 "free_verified": e.free_verified, "pricing": [e.input_price, e.output_price],
                 "pool": e.account_quota_pool, "disabled_reason": e.disabled_reason}
                for e in sorted(self.endpoints, key=lambda e: e.priority)
            ],
            "counters": {"attempts": self.attempts_total, "successes": self.successes,
                         "failures": self.failures},
        }


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (ValueError, TypeError):
        return False


