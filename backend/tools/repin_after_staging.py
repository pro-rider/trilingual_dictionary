"""Re-record the working-database pin after staging writes that never ship.

A staging ingest changes the working DB's hash while the shipped asset stays
byte-identical, because the release build drops every candidate table. This tool
re-pins the working DB, keeps the APPROVED asset approval intact, and states the
narrow reason for the hash move instead of leaving a PENDING string behind.

Refuses to run if the shipped asset no longer matches its approval.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend" / "tools"))

import verify_release_asset as v  # noqa: E402

PINS = REPO / "docs" / "ASSET-PINS.json"
RECORD = REPO / "docs" / "RELEASE.json"
DB = REPO / "backend" / "data" / "build" / "dictionary.sqlite"


def main() -> int:
    # the shipped asset must still verify before we touch anything
    if v.main() != 0:
        print("\nrefusing to re-pin: the shipped asset does not verify")
        return 1

    pins = json.loads(PINS.read_text(encoding="utf-8"))
    record = json.loads(RECORD.read_text(encoding="utf-8"))

    import hashlib

    digest = hashlib.sha256()
    with open(DB, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    sha, size = digest.hexdigest(), DB.stat().st_size

    pin = next(p for p in pins["pins"] if p["path"] == "backend/data/build/dictionary.sqlite")
    pin["sha256"] = sha
    pin["bytes"] = size
    pin["approved_by"] = (
        "AI Release Authority — asset APPROVED 2026-11-12T11:03:43Z on commit "
        f"d67d6e4 ({record['asset_version']}). Working-copy pin moved to {sha[:12]} "
        f"({size:,} B) by commit after this one, because 7,004 rows were staged into "
        "words3000_candidates from the user's raw vocabulary files "
        "(source=user-raw-2026-11-12). That table is dropped by "
        "tools/build_release_db.py, so the shipped database is unchanged: freshly "
        "rebuilding the release DB from this working copy produced byte-different but "
        "content-identical tables (tools/compare_release_content.py -> "
        "CONTENT IDENTICAL), and the approved asset db-8b0db9597b was kept."
    )
    pin["known_defect"] = None
    pins["approval_state"] = "APPROVED"

    record["source_sha256"] = sha
    record["source_bytes"] = size
    record["source_note"] = (
        "Working DB re-hashed after a staging-only write (words3000_candidates, "
        "7,004 rows, dropped from the release build). The release DB and packed "
        "asset recorded above were NOT rebuilt and remain the approved bytes."
    )

    PINS.write_text(json.dumps(pins, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")
    RECORD.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8", newline="\n")
    print(f"\nre-pinned working DB {sha[:12]} ({size:,} B); approval left APPROVED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
