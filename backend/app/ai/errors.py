"""Typed AI failures and their routing semantics.

Every failure carries three things the router needs:

* ``kind``      — one of the categories below, used for metrics and tests;
* ``retryable`` — may the *same* endpoint be called again inside the request;
* ``scope``     — what to cool down: the endpoint, its shared quota pool, or
  nothing at all (a permanent configuration error).

The rule that matters most: **unknown is treated as forbidden**. A failure we
cannot classify is not retried and does not count towards a paid fallback.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

import httpx

KINDS = {
    "rate_limit", "auth", "invalid_model", "timeout", "connection",
    "server", "parse", "content", "config", "unexpected", "free_policy",
}


class AIError(Exception):
    """Base class. ``message`` must already be safe to log (no secrets)."""

    kind = "unexpected"
    retryable = False
    scope = "none"          # "endpoint" | "pool" | "none"
    status_code: int | None = None
    retry_after: float | None = None

    def __init__(self, message: str, *, status_code: int | None = None,
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if retry_after is not None:
            self.retry_after = retry_after


class RateLimited(AIError):
    kind = "rate_limit"
    retryable = False        # the window persists; go to the next endpoint
    scope = "pool"           # quota is usually account-wide, not per model


class AuthFailed(AIError):
    kind = "auth"
    retryable = False
    scope = "endpoint"       # the credential is dead for this endpoint


class InvalidModel(AIError):
    kind = "invalid_model"
    retryable = False
    scope = "endpoint"       # retired / wrong identifier: don't hammer it


class ProviderTimeout(AIError):
    kind = "timeout"
    retryable = True
    scope = "endpoint"


class ConnectionFailed(AIError):
    kind = "connection"
    retryable = True
    scope = "endpoint"


class ServerError(AIError):
    kind = "server"
    retryable = True
    scope = "endpoint"


class ParseFailure(AIError):
    kind = "parse"
    retryable = True
    scope = "none"


class ContentRejected(AIError):
    kind = "content"
    retryable = False
    scope = "none"


class ConfigurationError(AIError):
    kind = "config"
    retryable = False
    scope = "none"


class FreePolicyViolation(AIError):
    kind = "free_policy"
    retryable = False
    scope = "endpoint"


@dataclass(frozen=True)
class Failure:
    kind: str
    retryable: bool
    scope: str
    message: str
    retry_after: float | None = None


_STATUS_KIND = {
    400: "invalid_model",   # parameter / model problem, permanent for this call
    401: "auth",
    403: "auth",
    404: "invalid_model",
    408: "timeout",
    409: "server",
    422: "invalid_model",
    429: "rate_limit",
    500: "server",
    502: "server",
    503: "server",
    504: "timeout",
}

_RETRYABLE = {"timeout", "connection", "server", "parse"}


def classify(exc: BaseException) -> Failure:
    """Map an exception to :class:`Failure`. Never raises."""
    if isinstance(exc, AIError):
        return Failure(exc.kind, exc.retryable, exc.scope,
                       str(exc.message)[:200], exc.retry_after)
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        kind = _STATUS_KIND.get(code, "server" if code >= 500 else "unexpected")
        retry_after = None
        raw = exc.response.headers.get("retry-after")
        if raw:
            try:
                retry_after = float(raw)
            except ValueError:
                retry_after = None
        scope = "pool" if kind == "rate_limit" else (
            "endpoint" if kind in {"auth", "invalid_model"} else "endpoint")
        return Failure(kind, kind in _RETRYABLE, scope,
                       f"HTTP {code}", retry_after)
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout,
                        httpx.PoolTimeout, TimeoutError)):
        return Failure("timeout", True, "endpoint", "timeout")
    if isinstance(exc, (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError,
                        socket.gaierror, ConnectionError)):
        return Failure("connection", True, "endpoint", "connection failed")
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        # almost always a malformed / unexpected payload
        return Failure("parse", True, "none", "malformed response")
    return Failure("unexpected", False, "none", type(exc).__name__)
