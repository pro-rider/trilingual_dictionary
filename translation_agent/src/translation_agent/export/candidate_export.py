"""Candidate export: approved rows only, deterministic manifest.

The agent exports; it never imports.  Importing is a parent-owned operation
performed outside this subsystem, against a copy, with pins verified.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..domain.identity import canonical_json, sha256_hex
from ..ledger.sqlite_ledger import CONTRACT_VERSION, SqliteLedger, utc_now


class ExportRefused(RuntimeError):
    pass


def export_approved(ledger: SqliteLedger, out_path: str) -> dict:
    rows = list(ledger.iter_candidates(state="approved"))
    if not rows:
        raise ExportRefused("no approved candidates to export")

    for row in rows:
        if row["state"] != "approved":
            raise ExportRefused(f"candidate {row['candidate_id']} is {row['state']}, not approved")

    payload = {
        "contract_version": CONTRACT_VERSION,
        "exported_at": utc_now(),
        "target_language": rows[0]["target_language"],
        "candidates": [
            {
                "candidate_id": row["candidate_id"],
                "sense_key": row["sense_key"],
                "target_language": row["target_language"],
                "text": row["original_text"],
                "normalized_text": row["normalized_text"],
                "normalization_version": row["normalization_version"],
                "candidate_hash": row["candidate_hash"],
                "request_id": row["request_id"],
                "batch_id": row["batch_id"],
            }
            for row in rows
        ],
    }
    payload["candidate_count"] = len(payload["candidates"])
    payload["export_checksum"] = sha256_hex(canonical_json(payload))

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload
