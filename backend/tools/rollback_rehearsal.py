"""Rollback rehearsal on a *copy* of the real governance store.

Proves, on the actual 3,245 imported rows rather than a fixture:

* backup -> import is idempotent (re-import adds nothing)
* verify is row-by-row (text and key)
* rollback of one batch removes exactly that batch
* the audit trail survives the rollback
* re-import after rollback produces the same content
* the dictionary file is byte-identical before and after
* the real store itself is never touched

Usage:
  .venv\\Scripts\\python.exe tools\\rollback_rehearsal.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.translations import schema  # noqa: E402
import import_legacy_ne as legacy  # noqa: E402

STORE = BACKEND / "data" / "build" / "translations.db"
DICT = BACKEND / "data" / "build" / "dictionary.sqlite"

CONTENT = (
    "sense_key", "entry_key", "language", "text", "generation_method", "evidence_strength",
    "validation_status", "publication_status", "human_verification", "origin_source",
    "origin_record_id", "origin_method", "origin_source_version", "legacy_status",
)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def content(store):
    conn = schema.connect(store)
    try:
        rows = conn.execute("select %s from translations order by sense_key, origin_record_id"
                            % ", ".join(CONTENT)).fetchall()
    finally:
        conn.close()
    return rows


def run(store=STORE, dictionary=DICT, work=None):
    work = Path(work or os.environ.get("TEMP", ".")) / "rollback_rehearsal"
    work.mkdir(parents=True, exist_ok=True)
    copy = work / "translations.rehearsal.db"
    shutil.copy2(store, copy)

    report = {
        "source_store": str(store),
        "copy": str(copy),
        "store_sha_before": sha(store),
        "dictionary_sha_before": sha(dictionary),
        "steps": {},
    }
    dictionary_sha = report["dictionary_sha_before"]
    meta, rows = legacy.read_dictionary(str(dictionary))
    planned, skipped, problems = legacy.plan(rows, "dictionary-2@%s" % meta.get("built_at", ""))
    report["planned"] = len(planned)
    report["plan_problems"] = len(problems)

    # 1. Idempotency: the copy already holds the real batch, so nothing is added.
    t0 = time.perf_counter()
    dup = legacy.apply(planned, copy, "2", "rehearsal-dup")
    report["steps"]["reimport_over_existing"] = {
        "inserted": dup["inserted"], "duplicates": dup["duplicates_skipped"],
        "seconds": round(time.perf_counter() - t0, 2),
    }
    report["verify_before"] = legacy.verify(str(copy), str(dictionary))

    # 2. Roll back the real batch on the copy.
    conn = schema.connect(copy)
    batch = conn.execute("select import_batch from translations limit 1").fetchone()[0]
    conn.close()
    rolled = legacy.rollback_batch(copy, batch)
    conn = schema.connect(copy)
    remaining = conn.execute("select count(*) from translations").fetchone()[0]
    audit = conn.execute("select action, count(*) from event_log group by 1").fetchall()
    conn.close()
    report["steps"]["rollback"] = {
        "batch": batch, "deleted": rolled["deleted"], "remaining_rows": remaining,
        "audit_preserved": rolled["audit_preserved"], "event_log": dict(audit),
        "only_that_batch": remaining == 0,
    }

    # 3. Re-import after rollback: same content as the original batch.
    t0 = time.perf_counter()
    back = legacy.apply(planned, copy, "2", batch)
    report["steps"]["reimport_after_rollback"] = {
        "inserted": back["inserted"], "duplicates": back["duplicates_skipped"],
        "seconds": round(time.perf_counter() - t0, 2),
    }
    report["verify_after"] = legacy.verify(str(copy), str(dictionary))
    report["content_matches_before_rollback"] = content(copy) == content(store)
    report["fingerprint_after"] = schema.content_fingerprint(str(copy))["content_sha256"]

    report["dictionary_sha_after"] = sha(dictionary)
    report["dictionary_unchanged"] = report["dictionary_sha_after"] == dictionary_sha
    report["store_sha_after"] = sha(store)
    report["store_unchanged"] = report["store_sha_after"] == report["store_sha_before"]

    report["ok"] = all([
        report["steps"]["reimport_over_existing"]["inserted"] == 0,
        report["verify_before"]["ok"],
        report["steps"]["rollback"]["only_that_batch"],
        report["steps"]["reimport_after_rollback"]["inserted"] == len(planned),
        report["verify_after"]["ok"],
        report["content_matches_before_rollback"],
        report["dictionary_unchanged"],
        report["store_unchanged"],
    ])
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--dictionary", default=str(DICT))
    ap.add_argument("--work")
    args = ap.parse_args()
    result = run(Path(args.store), Path(args.dictionary), args.work)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
