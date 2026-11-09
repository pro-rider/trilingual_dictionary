"""Raw provider response retention.

Separate from candidate rows on purpose: deleting raw payloads must never
delete a candidate, and deleting a candidate must never destroy the audit
trail.  Payloads are redacted and size-capped before they touch disk.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

REDACTED = "[REDACTED]"

# (pattern, replacement) — keep the label, drop the secret.
_SECRET_RULES = (
    (re.compile(r"sk-[A-Za-z0-9\-_]{8,}"), REDACTED),
    (re.compile(r"AIza[0-9A-Za-z\-_]{10,}"), REDACTED),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-_.]{8,}"), r"\1" + REDACTED),
    (re.compile(r"((?:api[_-]?key|apikey)\s*[=:]\s*)[\"']?[A-Za-z0-9\-_.]{8,}"), r"\1" + REDACTED),
)


def redact(payload: str) -> str:
    text = payload
    for pattern, replacement in _SECRET_RULES:
        text = pattern.sub(replacement, text)
    return text


def prepare_response(
    *,
    request_id: str,
    payload: str,
    max_bytes: int,
    retention_days: int,
) -> dict:
    cleaned = redact(payload)
    encoded = cleaned.encode("utf-8")
    truncated = False
    if len(encoded) > max_bytes:
        cleaned = encoded[:max_bytes].decode("utf-8", errors="ignore")
        encoded = cleaned.encode("utf-8")
        truncated = True
    return {
        "request_id": request_id,
        "payload": cleaned,
        "bytes": len(encoded),
        "truncated": 1 if truncated else 0,
        "retention_days": retention_days,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
