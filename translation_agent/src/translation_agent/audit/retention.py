"""Explicit raw-response retention.

``retention_days`` used to be a stored integer with no enforcement.  Retention
is now an operation a human triggers — never something a generation run does
silently — that erases payload bytes and keeps the row, the request linkage and
the audit history intact.

Deleting the row would destroy evidence that the request happened; deleting the
candidate would destroy the work.  Only the payload is transient.
"""

from __future__ import annotations

from datetime import datetime

from ..ledger.sqlite_ledger import SqliteLedger


def plan_retention(ledger: SqliteLedger, now: datetime | None = None) -> dict:
    expired = ledger.expired_raw_responses(now)
    return {
        "expired": len(expired),
        "response_ids": [row["response_id"] for row in expired],
        "requests": sorted({row["request_id"] for row in expired}),
        "candidates_affected": 0,
    }


def apply_retention(ledger: SqliteLedger, now: datetime | None = None) -> dict:
    plan = plan_retention(ledger, now)
    purged = ledger.purge_raw_payloads(plan["response_ids"], reason="retention")
    return {**plan, "purged": purged}
