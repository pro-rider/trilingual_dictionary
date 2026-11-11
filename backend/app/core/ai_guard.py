"""Runtime guards for the AI-backed endpoints (task P0.5).

Three jobs, all deliberately cheap and reversible:

1. ``ai_runtime_enabled()`` — a kill switch that takes effect **without a restart**.
   The flag file (``AI_ENABLED_FILE``, default ``.ai_enabled`` next to the backend
   package) is re-read on every call: create it to enable, delete it to stop. An
   explicit ``AI_RUNTIME_ENABLED`` env var overrides the file when set.
2. ``require_ai_access`` — a shared-secret header so a stray local process cannot
   spend the free provider quota. **No secret configured = current behaviour**
   (the loops still run), which is why this is safe to ship before the Flutter
   client learns to send the header.
3. ``enforce_limits`` — in-memory per-client and global sliding window plus a
   daily request ceiling. Defaults are non-zero (60/min, 2000/day) so a
   production deployment is limited out of the box instead of inheriting "no
   limiter at all" because nobody set a value. The limiter counts every call to
   a guarded route, whether or not AI answers it, because the gate belongs at
   the boundary rather than at the spend site.

Nothing here logs user text: only counts, client keys and status codes.
"""

from __future__ import annotations

import hmac
import os
import time
from pathlib import Path

from fastapi import Header, HTTPException

from app.core.config import settings

# --- tunables, read from the environment on every call so tests and an operator
# --- can change them without reloading the process -------------------------------

_DEFAULT_FLAG_FILE = Path(__file__).resolve().parents[2] / ".ai_enabled"

_TRUTHY = {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, fallback: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return fallback
    try:
        return int(raw.strip())
    except ValueError:
        return fallback


def _flag_file() -> Path:
    raw = os.environ.get("AI_ENABLED_FILE")
    return Path(raw) if raw else _DEFAULT_FLAG_FILE


def ai_runtime_enabled() -> bool:
    """True when AI may be used right now. Re-read per call — no restart needed."""
    override = os.environ.get("AI_RUNTIME_ENABLED")
    if override is not None and override.strip():
        return override.strip().lower() in _TRUTHY
    if _flag_file().exists():
        return True
    return bool(settings.ai_enabled)


def _shared_secret() -> str:
    return (os.environ.get("AI_SHARED_SECRET") or settings.ai_shared_secret or "").strip()


def require_ai_access(x_ai_token: str | None = Header(default=None, alias="X-AI-Token")) -> None:
    """Dependency: enforce the shared secret when one is configured.

    Constant-time comparison, and the configured value is never echoed back.
    """
    secret = _shared_secret()
    if not secret:
        return  # no secret configured: behave as before
    if not x_ai_token or not hmac.compare_digest(x_ai_token, secret):
        raise HTTPException(status_code=401, detail="AI access token missing or invalid")


# --- limits ---------------------------------------------------------------------


class _SlidingWindow:
    """Per-key timestamps inside one minute, plus a process-wide daily counter."""

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._day: str = ""
        self._day_count: int = 0

    def allow(self, key: str, per_minute: int, daily_cap: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        today = time.strftime("%Y-%m-%d", time.localtime())
        if today != self._day:
            self._day = today
            self._day_count = 0

        if daily_cap > 0 and self._day_count >= daily_cap:
            return False

        if per_minute > 0:
            bucket = [t for t in self._hits.get(key, []) if now - t < 60.0]
            if len(bucket) >= per_minute:
                self._hits[key] = bucket
                return False
            bucket.append(now)
            self._hits[key] = bucket

        if daily_cap > 0:
            self._day_count += 1
        return True

    def reset(self) -> None:
        self._hits.clear()
        self._day = ""
        self._day_count = 0


limiter = _SlidingWindow()


def enforce_limits(
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
) -> None:
    """Dependency: 429 when a client or the whole process exceeds its quota."""
    per_minute = _env_int("AI_RATE_LIMIT_PER_MIN", settings.ai_rate_limit_per_min)
    daily_cap = _env_int("AI_DAILY_CAP", settings.ai_daily_cap)
    if per_minute <= 0 and daily_cap <= 0:
        return
    key = (x_client_id or "anonymous").strip()[:64] or "anonymous"
    if not limiter.allow(key, per_minute, daily_cap):
        raise HTTPException(
            status_code=429,
            detail="Usage limit reached. Please try again later.",
        )
