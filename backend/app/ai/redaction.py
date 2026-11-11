"""Keep credentials out of logs, stats and API responses.

Two layers: exact-value redaction (we know the configured keys) and pattern
redaction (authorization headers, ``key=``, ``sk-…`` shapes) so an unknown
secret pasted into an error message still cannot leak.
"""

from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(x-api-key\s*[:=]\s*)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)([?&](?:key|api_key|token)=)[A-Za-z0-9._\-]{6,}"),
    re.compile(r"\b(sk|gsk|or|aiza)[-_][A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{10,}\b"),
]

_registry: set[str] = set()


def register_secret(value: str | None) -> None:
    """Remember a real credential so it can be scrubbed by value."""
    if value and len(value) >= 8:
        _registry.add(value)


def redact(text: str | None, *, limit: int = 200) -> str:
    if not text:
        return ""
    out = str(text)
    for secret in _registry:
        out = out.replace(secret, "[REDACTED]")
    for rx in _PATTERNS:
        out = rx.sub(lambda m: (m.group(1) or "") + "[REDACTED]", out)
    return out[:limit]
