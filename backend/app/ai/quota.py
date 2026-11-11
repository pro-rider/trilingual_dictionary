"""Quota tracking for free tiers.

The mistake this avoids: treating twelve free models behind one OpenRouter key
as twelve independent quota pools. They share one account pool, so exhaustion
must block all of them at once.

Counters live in memory and, when a state file is configured, are flushed to
JSON so a process restart does not silently hand out a fresh daily allowance
(the file defaults to the OS temp dir, never inside the repository).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PoolState:
    rpm_used: list[float] = field(default_factory=list)   # monotonic stamps
    day_key: str = ""
    day_used: int = 0
    exhausted_until: float = 0.0                          # monotonic
    last_quota_error: str = ""
    unknown_limits: bool = True

    def day_now(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime())


class QuotaTracker:
    """Conservative, per-pool limiter.

    Limits default to conservative numbers when the provider does not publish
    them, and ``unknown_limits`` stays True so reports never claim we knew the
    real allowance. Nothing here is a guarantee of remaining capacity: it is a
    guard against the router itself burning a free tier dry.
    """

    def __init__(self, *, state_file: str | Path | None = None,
                 default_rpm: int = 20, default_rpd: int = 1000,
                 clock=time.monotonic, wall=time.time) -> None:
        self._state_file = Path(state_file) if state_file else None
        self.default_rpm = max(1, default_rpm)
        self.default_rpd = max(1, default_rpd)
        self._clock = clock
        self._wall = wall
        self._pools: dict[str, PoolState] = {}
        self._lock = threading.Lock()
        self._load()

    # ---------------------------------------------------------------- pools
    def pool(self, name: str) -> PoolState:
        st = self._pools.get(name)
        if st is None:
            st = PoolState()
            self._pools[name] = st
        return st

    def seconds_until_reset(self, name: str) -> float:
        st = self.pool(name)
        now = self._clock()
        if st.exhausted_until > now:
            return max(0.0, st.exhausted_until - now)
        return 0.0

    def allow(self, name: str, *, rpm: int | None = None, rpd: int | None = None) -> bool:
        """True when one more request fits in the window."""
        rpm = self.default_rpm if rpm is None else max(1, rpm)
        rpd = self.default_rpd if rpd is None else max(1, rpd)
        st = self.pool(name)
        with self._lock:
            now = self._clock()
            if st.exhausted_until > now:
                return False
            today = st.day_now()
            if today != st.day_key:
                st.day_key = today
                st.day_used = 0
            if st.day_used >= rpd:
                st.exhausted_until = now + 3600.0
                st.last_quota_error = "daily cap reached (configured)"
                return False
            st.rpm_used = [t for t in st.rpm_used if now - t < 60.0]
            if len(st.rpm_used) >= rpm:
                return False
            return True

    def acquire(self, name: str, *, rpm: int | None = None,
                rpd: int | None = None) -> bool:
        """Atomically check *and* spend one request.

        ``allow()`` followed later by ``record_request()`` is a TOCTOU window:
        under concurrency N requests all see the last free slot and all send.
        """
        rpm = self.default_rpm if rpm is None else max(1, rpm)
        rpd = self.default_rpd if rpd is None else max(1, rpd)
        st = self.pool(name)
        with self._lock:
            now = self._clock()
            if st.exhausted_until > now:
                return False
            today = st.day_now()
            if today != st.day_key:
                st.day_key = today
                st.day_used = 0
            if st.day_used >= rpd:
                st.exhausted_until = now + 3600.0
                st.last_quota_error = "daily cap reached (configured)"
                self._flush_unlocked()
                return False
            st.rpm_used = [t for t in st.rpm_used if now - t < 60.0]
            if len(st.rpm_used) >= rpm:
                # Persist before refusing: the earlier spend in this window is
                # still real, and a restart must not forget it.
                self._flush_unlocked()
                return False
            st.rpm_used.append(now)
            st.day_used += 1
            # Every accepted request is persisted, not only an exhaustion event.
            # Before this, a crash or restart silently returned the day's spent
            # allowance, contradicting the promise at the top of this module.
            self._flush_unlocked()
            return True

    def record_quota_exhausted(self, name: str, seconds: float,
                               message: str = "quota exhausted") -> None:
        st = self.pool(name)
        with self._lock:
            st.exhausted_until = max(st.exhausted_until,
                                     self._clock() + max(1.0, seconds))
            st.last_quota_error = message[:120]
        self._flush()

    def snapshot(self) -> dict:
        out = {}
        now = self._clock()
        for name, st in self._pools.items():
            out[name] = {
                "requests_this_minute": len([t for t in st.rpm_used if now - t < 60.0]),
                "requests_today": st.day_used,
                "exhausted_for_seconds": round(self.seconds_until_reset(name), 1),
                "unknown_limits": st.unknown_limits,
                "last_quota_error": st.last_quota_error,
            }
        return out

    # ----------------------------------------------------------- persistence
    def _load(self) -> None:
        if not self._state_file or not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for name, raw in (data.get("pools") or {}).items():
            st = self.pool(name)
            st.day_key = raw.get("day_key", "")
            st.day_used = int(raw.get("day_used", 0))
            st.unknown_limits = bool(raw.get("unknown_limits", True))

    def persist(self) -> None:
        self._flush()

    def _flush(self) -> None:
        with self._lock:
            self._flush_unlocked()

    def _flush_unlocked(self) -> None:
        if not self._state_file:
            return
        payload = {"pools": {n: {"day_key": s.day_key, "day_used": s.day_used,
                                 "unknown_limits": s.unknown_limits}
                             for n, s in self._pools.items()}}
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, self._state_file)
        except OSError:
            pass


def default_state_file() -> Path:
    return Path(tempfile.gettempdir()) / "trilingual_ai_quota.json"
