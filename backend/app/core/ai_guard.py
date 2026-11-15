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

import hashlib
import hmac
import ipaddress
import logging
import os
import time
from pathlib import Path

from fastapi import Header, HTTPException, Request

from app.core import net
from app.core.config import settings
from app.core.security import optional_uid

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


def _ip_bucket(request: Request) -> str:
    """The address (IPv4) or /64 network (IPv6) a caller is counted against.

    One attacker usually controls a whole /64, so keying on a single IPv6
    address would let them rotate through billions of addresses and never hit
    a per-IP cap. The address itself is already resolved through the trusted
    proxy rules in `app.core.net`.
    """
    raw = net.client_ip(request) if request is not None else ""
    if not raw:
        return "unknown"
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return "unknown"
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def _label_hash(label: str | None) -> str:
    if not label or not label.strip():
        return ""
    return hashlib.sha256(label.strip().encode()).hexdigest()[:16]


def _identity_buckets(request: Request, label: str | None) -> list[tuple[str, int]]:
    """(bucket, daily cap) pairs that must all pass.

    Signed-in users are keyed by their uid. Guests are keyed by the install id
    *and* by the IP bucket, so deleting the install id resets only one counter:
    rotating a client-supplied header cannot buy unlimited quota (this was the
    flaw in keying on `X-Client-Id` alone). Neither value is stored or logged.
    """
    uid = optional_uid(request.headers.get("authorization") if request is not None else None)
    if uid:
        cap = _env_int("AI_DAILY_CAP_PER_USER", settings.ai_user_daily_cap)
        return [(f"user:{uid}", cap)]

    guest_cap = _env_int("AI_DAILY_CAP_PER_GUEST", settings.ai_guest_daily_cap)
    bucket = _ip_bucket(request)
    pairs: list[tuple[str, int]] = []
    label = _label_hash(label)
    if label:
        pairs.append((f"guest:{bucket}:{label}", guest_cap))
    elif bucket != "unknown":
        pairs.append((f"guest:{bucket}", guest_cap))
    if bucket != "unknown":
        multiplier = _env_int("AI_GUEST_BUCKET_MULTIPLIER", settings.ai_guest_bucket_multiplier)
        pairs.append((f"guest-net:{bucket}", guest_cap * max(1, multiplier)))
    return pairs or [("guest:unknown", guest_cap)]


def enforce_limits(
    request: Request,
    x_install_id: str | None = Header(default=None, alias="X-Install-Id"),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
) -> None:
    """Dependency: 429 when a caller or the whole process exceeds its quota.

    Option B: guests get a small daily allowance, signed-in users a larger one,
    and a process-wide ceiling protects the provider budget. The primary key
    comes from the caller's identity, never from a header alone; `X-Client-Id`
    is accepted only as a legacy alias for the install id, and the IP bucket
    caps that alias anyway.
    """
    per_minute = _env_int("AI_RATE_LIMIT_PER_MIN", settings.ai_rate_limit_per_min)
    global_per_minute = _env_int("AI_RATE_LIMIT_GLOBAL_PER_MIN",
                                 settings.ai_rate_limit_global_per_min)
    global_daily_cap = _env_int("AI_DAILY_CAP", settings.ai_daily_cap)

    buckets = _identity_buckets(request, x_install_id or x_client_id)
    if all(cap <= 0 for _key, cap in buckets) and per_minute <= 0 \
            and global_per_minute <= 0 and global_daily_cap <= 0:
        return

    for key, daily_cap in buckets:
        allowed, reason = limiter.allow(
            key, per_minute, daily_cap, global_per_minute, global_daily_cap
        )
        if not allowed:
            logger.info("ai limit hit: scope=%s key_class=%s", reason, key.split(":")[0])
            raise HTTPException(
                status_code=429,
                detail="Usage limit reached. Please try again later.",
            )
