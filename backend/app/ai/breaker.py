"""Circuit breakers with the three states the spec asks for.

CLOSED  → requests flow; consecutive failures count up.
OPEN    → requests are skipped until ``open_until`` passes.
HALF_OPEN → exactly one probe is allowed; success closes, failure re-opens.

A breaker exists per endpoint *and* per quota pool, because a shared account
quota (one OpenRouter key feeding twelve free models) goes down for all of
them at once — twelve model-level breakers cannot express that.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class Breaker:
    fail_threshold: int = 3
    cooldown_seconds: float = 60.0
    open_until: float = 0.0
    consecutive_failures: int = 0
    state: str = "closed"
    half_open_in_flight: bool = False
    last_error: str = ""
    opened_count: int = 0
    # Serialises allow()/record_*: without it two threads can both take the
    # single half-open probe, and failure counters can be lost.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False,
                                  compare=False)

    def _now(self) -> float:
        return time.monotonic()

    def allow(self) -> bool:
        with self._lock:
            now = self._now()
            if self.state == "open" and now >= self.open_until:
                self.state = "half_open"
                self.half_open_in_flight = False
            if self.state == "open":
                return False
            if self.state == "half_open":
                if self.half_open_in_flight:
                    return False
                self.half_open_in_flight = True
                return True
            return True

    def record_success(self) -> None:
        with self._lock:
            self.state = "closed"
            self.consecutive_failures = 0
            self.half_open_in_flight = False
            self.last_error = ""

    def record_failure(self, message: str, *, cooldown: float | None = None,
                       permanent: bool = False) -> None:
        with self._lock:
            self.consecutive_failures += 1
            self.last_error = message[:160]
            self.half_open_in_flight = False
            cd = self.cooldown_seconds if cooldown is None else cooldown
            if permanent or self.state == "half_open" or \
                    self.consecutive_failures >= self.fail_threshold:
                self.state = "open"
                self.open_until = self._now() + max(1.0, cd)
                self.opened_count += 1

    def snapshot(self) -> dict:
        with self._lock:
            now = self._now()
            return {
                "state": self.state,
                "consecutive_failures": self.consecutive_failures,
                "open_for_seconds": max(0.0, round(self.open_until - now, 1))
                if self.state == "open" else 0.0,
                "opened_count": self.opened_count,
                "last_error": self.last_error,
            }


HALF_OPEN = "half_open"
CLOSED = "closed"
OPEN = "open"


@dataclass
class BreakerBoard:
    """One breaker per key (endpoint id or quota-pool name)."""

    fail_threshold: int = 3
    cooldown_seconds: float = 60.0
    _items: dict[str, Breaker] = field(default_factory=dict)

    def get(self, key: str) -> Breaker:
        b = self._items.get(key)
        if b is None:
            b = Breaker(fail_threshold=self.fail_threshold,
                        cooldown_seconds=self.cooldown_seconds)
            self._items[key] = b
        return b

    def allow(self, key: str) -> bool:
        return self.get(key).allow()

    def snapshot(self) -> dict[str, dict]:
        return {k: v.snapshot() for k, v in self._items.items()}
