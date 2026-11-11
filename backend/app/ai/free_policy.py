"""Strict zero-cost policy.

One function decides whether an endpoint may be called. It is deliberately
narrow and returns a *reason* rather than a bool, because "why was this model
skipped" is the question people actually ask later.

Fail-closed rules:
* ``free_verified`` must be True;
* ``input_price`` and ``output_price`` must be numeric **0** (``None`` = unknown
  = not free);
* no ``disabled_reason``;
* an API key must be configured.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.errors import FreePolicyViolation
from app.ai.registry import ModelEndpoint


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""

    def raise_if_denied(self, key: str) -> None:
        if not self.allowed:
            raise FreePolicyViolation(f"{key}: {self.reason}")


def decide(ep: ModelEndpoint, *, free_only: bool = True) -> Decision:
    if ep.disabled_reason:
        return Decision(False, ep.disabled_reason)
    if free_only:
        if not ep.free_verified:
            return Decision(False, "free eligibility not verified")
        if ep.input_price is None or ep.output_price is None:
            return Decision(False, "pricing unknown - treated as paid")
        if ep.input_price != 0 or ep.output_price != 0:
            return Decision(False, f"non-zero price (in={ep.input_price}, out={ep.output_price})")
    if not ep.configured:
        return Decision(False, f"missing credential {ep.api_key_env}")
    return Decision(True)


def allowed_candidates(endpoints: list[ModelEndpoint], *, free_only: bool = True) -> list[ModelEndpoint]:
    kept = [e for e in endpoints if decide(e, free_only=free_only).allowed]
    return sorted(kept, key=lambda e: e.priority)
