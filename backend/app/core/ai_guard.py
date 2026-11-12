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
import logging
import os
import time
from pathlib import Path

from fastapi import Header, HTTPException, Request

from app.core.config import settings

logger = logging.getLogger(__name__)

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
    """Sliding per-minute buckets plus daily counters, per key and global.

    Two budgets exist on purpose: a per-client budget (one device or one IP) and
    a separate process-wide budget. With only a global counter, a single heavy
    client takes AI away from everybody else for the rest of the day; with only
    per-client counters, a botnet or a shared IP can exhaust the provider quota.
    """

    GLOBAL_KEY = "__global__"

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._client_day: dict[str, int] = {}
        self._day: str = ""
        self._day_count: int = 0

    def _roll_day(self) -> None:
        today = time.strftime("%Y-%m-%d", time.localtime())
        if today != self._day:
            self._day = today
            self._day_count = 0
            self._client_day.clear()

    def allow(self, key: str, per_minute: int, daily_cap: int,
              global_per_minute: int = 0, global_daily_cap: int = 0,
              now: float | None = None) -> tuple[bool, str]:
        """Return (allowed, reason). The reason is for logs, never for the user."""
        now = time.monotonic() if now is None else now
        self._roll_day()

        if daily_cap > 0 and self._client_day.get(key, 0) >= daily_cap:
            return False, "client_daily_cap"
        if global_daily_cap > 0 and self._day_count >= global_daily_cap:
            return False, "global_daily_cap"

        for bucket_key, limit, label in (
            (key, per_minute, "client_rate"),
            (self.GLOBAL_KEY, global_per_minute, "global_rate"),
        ):
            if limit <= 0:
                continue
            bucket = [t for t in self._hits.get(bucket_key, []) if now - t < 60.0]
            if len(bucket) >= limit:
                self._hits[bucket_key] = bucket
                return False, label
            bucket.append(now)
            self._hits[bucket_key] = bucket

        if daily_cap > 0:
            self._client_day[key] = self._client_day.get(key, 0) + 1
        if global_daily_cap > 0:
            self._day_count += 1
        return True, ""

    def reset(self) -> None:
        self._hits.clear()
        self._client_day.clear()
        self._day = ""
        self._day_count = 0


limiter = _SlidingWindow()


def _client_key(request: Request, x_client_id: str | None) -> str:
    """Prefer the app's device id, fall back to the caller's IP address.

    Without the fallback every anonymous caller shares the single key
    ``anonymous`` and one of them can lock the rest out.
    """
    if x_client_id and x_client_id.strip():
        return "dev:" + x_client_id.strip()[:64]
    host = ""
    if request is not None and request.client is not None:
        host = request.client.host or ""
    return "ip:" + (host or "unknown")[:64]


def enforce_limits(
    request: Request,
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
) -> None:
    """Dependency: 429 when a client or the whole process exceeds its quota."""
    per_minute = _env_int("AI_RATE_LIMIT_PER_MIN", settings.ai_rate_limit_per_min)
    daily_cap = _env_int("AI_DAILY_CAP_PER_CLIENT", settings.ai_daily_cap_per_client)
    global_per_minute = _env_int("AI_RATE_LIMIT_GLOBAL_PER_MIN",
                                 settings.ai_rate_limit_global_per_min)
    global_daily_cap = _env_int("AI_DAILY_CAP", settings.ai_daily_cap)
    if all(v <= 0 for v in (per_minute, daily_cap, global_per_minute, global_daily_cap)):
        return
    key = _client_key(request, x_client_id)
    allowed, reason = limiter.allow(
        key, per_minute, daily_cap, global_per_minute, global_daily_cap
    )
    if not allowed:
        logger.info("ai limit hit: scope=%s key=%s", reason, key)
        raise HTTPException(
            status_code=429,
            detail="Usage limit reached. Please try again later.",
        )
