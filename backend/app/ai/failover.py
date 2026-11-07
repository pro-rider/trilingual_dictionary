"""Multi-provider LLM failover service.

Runs the providers in priority order (Groq → Gemini → OpenRouter by default),
with per-provider retries, a circuit breaker that temporarily disables a
repeatedly-failing provider, rate-limit (429) skipping, per-provider metrics
and structured logging of every failure and success.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.ai.base import LLMProvider, ProviderRateLimit

logger = logging.getLogger("app.ai.failover")


@dataclass
class CircuitState:
    """Per-provider state: metrics + circuit breaker."""

    consecutive_failures: int = 0
    open_until: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    last_error: str = ""
    last_latency_ms: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.open_until > time.monotonic()

    def avg_latency_ms(self) -> float:
        calls = self.success_count + self.failure_count
        return self.total_latency_ms / calls if calls else 0.0


class FailoverLLMService:
    """Falls through the provider chain until one answers."""

    def __init__(
        self,
        providers: list[LLMProvider],
        order: list[str],
        *,
        max_retries: int,
        retry_backoff: float,
        fail_threshold: int,
        cooldown_seconds: int,
    ) -> None:
        self._by_name = {p.name: p for p in providers}
        self._order = [n for n in order if n in self._by_name]
        self.max_retries = max(0, max_retries)
        self.retry_backoff = retry_backoff
        self.fail_threshold = max(1, fail_threshold)
        self.cooldown_seconds = max(1, cooldown_seconds)
        self.circuits = {p.name: CircuitState() for p in providers}

    # ------------------------------------------------------------------ public

    def active_providers(self) -> list[str]:
        return [n for n in self._order if self._by_name[n].active]

    def complete(self, system_prompt: str) -> tuple[str | None, str, dict]:
        """Run the chain. Returns ``(text, provider_name, stats)``.

        ``text`` is ``None`` when every provider failed (graceful degradation);
        ``provider_name`` is the winner, or ``"none"``.
        """
        for name in self._order:
            provider = self._by_name[name]
            circuit = self.circuits[name]
            if not provider.active:
                logger.debug("LLM provider '%s' skipped (disabled / no key)", name)
                continue
            if circuit.is_open:
                logger.warning(
                    "LLM provider '%s' skipped (circuit open, %.0fs left)",
                    name,
                    circuit.open_until - time.monotonic(),
                )
                continue

            text, err = self._run_with_retries(provider, system_prompt)
            if text is not None:
                circuit.success_count += 1
                logger.info(
                    "LLM provider '%s' answered in %.0fms",
                    name,
                    circuit.last_latency_ms,
                )
                return text, name, self.stats()

            # Failure: update breaker + metrics.
            circuit.failure_count += 1
            circuit.consecutive_failures += 1
            circuit.last_error = err or "unknown"
            if circuit.consecutive_failures >= self.fail_threshold:
                circuit.open_until = time.monotonic() + self.cooldown_seconds
                logger.error(
                    "LLM provider '%s' circuit OPEN after %d failures (last: %s)",
                    name,
                    circuit.consecutive_failures,
                    err,
                )
            logger.error(
                "LLM provider '%s' failed after %d attempts: %s",
                name,
                self.max_retries + 1,
                err or "no response",
            )

        # All providers failed.
        logger.critical(
            "ALL LLM providers failed. Chain=%s", self.active_providers()
        )
        return None, "none", self.stats()

    def stats(self) -> dict:
        return {
            "chain": self._order,
            "active": self.active_providers(),
            "max_retries": self.max_retries,
            "providers": {
                name: self._provider_stats(name) for name in self._order
            },
        }

    # ------------------------------------------------------------- internals

    def _run_with_retries(
        self, provider: LLMProvider, system_prompt: str
    ) -> tuple[str | None, str]:
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            start = time.perf_counter()
            try:
                text = provider.complete(system_prompt)
            except ProviderRateLimit as exc:
                self._record_latency(provider, start)
                # Rate limits persist for a short window — route to next now.
                return None, str(exc)
            latency_ms = (time.perf_counter() - start) * 1000.0
            self.circuits[provider.name].last_latency_ms = latency_ms
            self.circuits[provider.name].total_latency_ms += latency_ms
            if text is not None:
                return text, ""
            if attempt < attempts - 1:
                time.sleep(self.retry_backoff)
        return None, "empty response"

    def _record_latency(self, provider: LLMProvider, start: float) -> None:
        latency_ms = (time.perf_counter() - start) * 1000.0
        self.circuits[provider.name].last_latency_ms = latency_ms
        self.circuits[provider.name].total_latency_ms += latency_ms

    def _provider_stats(self, name: str) -> dict:
        c = self.circuits[name]
        p = self._by_name[name]
        return {
            "enabled": p.enabled,
            "active": p.active,
            "model": p.model,
            "timeout": p.timeout,
            "circuit_open": c.is_open,
            "success_count": c.success_count,
            "failure_count": c.failure_count,
            "consecutive_failures": c.consecutive_failures,
            "avg_latency_ms": round(c.avg_latency_ms(), 1),
            "last_latency_ms": round(c.last_latency_ms, 1),
            "last_error": c.last_error,
        }
