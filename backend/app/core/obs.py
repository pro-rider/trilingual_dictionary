"""Structured operational logging and alerting hooks (Phase 10).

The backend already logs with `%s`-style messages. What was missing was a way to
answer "how is the AI subsystem doing right now", and a place an alert would be
sent from. This module provides both without adding a dependency:

* ``log_event(event, **fields)`` writes one JSON line, so log collection can
  parse it. It refuses keys whose value looks like user text — the project rule
  is that no user text is logged, ever. Only identifiers, counts and durations
  are accepted.
* ``note_ai_attempt(ok)`` keeps in-process counters, and
  ``ai_failure_rate()`` / ``snapshot()`` expose them.
* ``set_alert_hook(fn)`` lets a deployment plug in a webhook later. Nothing is
  sent by default, so a fresh install cannot accidentally phone home.

Invariants: no user text, no API keys, no IP addresses in these records.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from collections import deque
from typing import Any, Callable

logger = logging.getLogger("obs")

_ALLOWED_FIELDS = {
    "event", "kind", "endpoint", "attempt", "latency_ms", "status",
    "count", "reason", "scope", "route", "method", "duration_ms", "model",
    "provider", "tier", "rows", "total",
}
_MAX_FIELD_TEXT = 64

_lock = threading.RLock()  # reentrant: helpers call log_event while holding it
_events: deque[tuple[float, dict[str, Any]]] = deque(maxlen=500)
_counters = {"attempts": 0, "ok": 0, "failed": 0}
_alert_hook: Callable[[dict[str, Any]], None] | None = None


def _safe(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop anything that is not an approved field, and clip long values.

    An accidental `text=` or `query=` would violate the no-user-text rule, so
    unknown keys are dropped rather than logged.
    """
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in _ALLOWED_FIELDS:
            continue
        if isinstance(value, str):
            out[key] = value[:_MAX_FIELD_TEXT]
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
    return out


def log_event(event: str, **fields: Any) -> dict[str, Any]:
    record = {"ts": round(time.time(), 3), "event": event, **_safe(fields)}
    with _lock:
        _events.append((time.time(), record))
    try:
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 - logging must never break a request
        logger.debug("obs write failed")
    return record


def note_ai_attempt(ok: bool, **fields: Any) -> None:
    with _lock:
        _counters["attempts"] += 1
        _counters["ok" if ok else "failed"] += 1
    log_event("ai_attempt", status=("ok" if ok else "error"), **fields)


def ai_failure_rate(window_seconds: float = 600.0) -> float:
    """Failure ratio over the recent window; 0.0 when nothing happened."""
    since = time.time() - window_seconds
    with _lock:
        recent = [r for ts, r in _events if ts >= since and r.get("event") == "ai_attempt"]
    if not recent:
        return 0.0
    failed = sum(1 for r in recent if r.get("status") != "ok")
    return failed / len(recent)


def snapshot() -> dict[str, Any]:
    with _lock:
        return {**_counters, "failure_rate_10m": round(ai_failure_rate(), 4),
                "recent_events": len(_events)}


def set_alert_hook(hook: Callable[[dict[str, Any]], None] | None) -> None:
    global _alert_hook
    _alert_hook = hook


def maybe_alert(threshold: float = 0.8, minimum_attempts: int = 10) -> bool:
    """Fire the hook when the AI chain is failing wholesale.

    Returns True when an alert was emitted, so a caller (or a test) can check it
    without inspecting the hook.
    """
    rate = ai_failure_rate()
    with _lock:
        attempts = _counters["attempts"]
    if attempts < minimum_attempts or rate < threshold:
        return False
    payload = {"event": "ai_failure_rate_alert", "failure_rate": round(rate, 3),
               "attempts": attempts, **snapshot()}
    log_event("ai_failure_rate_alert", failure_rate=round(rate, 3), count=attempts)
    if _alert_hook is not None:
        try:
            _alert_hook(payload)
        except Exception:  # noqa: BLE001
            logger.warning("alert hook failed")
    return True


def reset_for_tests() -> None:
    with _lock:
        _events.clear()
        _counters.update(attempts=0, ok=0, failed=0)
