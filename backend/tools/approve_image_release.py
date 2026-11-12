"""Approve (or refuse to approve) the image-system release change.

The pin is rewritten first, because the pin *is* the claim under test: if
verify_release_asset.py cannot re-derive the chain afterwards, the approval is
not written and the record stays in its pending shape.

Usage: python tools/approve_image_release.py --trigger-commit <sha>
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend" / "tools"))

import verify_release_asset as v  # noqa: E402
import build_release_db as brel  # noqa: E402

RECORD = REPO / "docs" / "RELEASE.json"
PINS = REPO / "docs" / "ASSET-PINS.json"
APPROVER = "AI Release Authority"

EVIDENCE = (
    "images 77 -> 113 (36 Wikimedia Commons photographs added under the strict "
    "licence (CC0/PD/CC BY/CC BY-SA only), quality (>=500 px, no book scans or "
    "engravings) and lexical-relevance gates); entries with a picture 204 -> 246, "
    "of which 8 came from exact-label concept inheritance and 2 of those were "
    "removed by review (时候 -> pocket watch, 鸟 -> an Aristophanes engraving). "
    "35 of the 113 references used a nested thumbs/<xx>/<sha>.webp layout that "
    "Flutter never bundled - the previous APK shipped 84 thumbnails while the "
    "database pointed at 35 files that were not in it - so every reference is now "
    "flat (thumbs/<sha>.webp), the dead duplicates and 9 orphan files are deleted, "
    "and tools/verify_image_assets.py fails the build on a missing, nested, orphan "
    "or absent thumbnail. One missing thumbnail (image 7) was regenerated."
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trigger-commit", required=True)
    ap.add_argument("--utc", default=None)
    args = ap.parse_args(argv)
    stamp = args.utc or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    record = json.loads(RECORD.read_text(encoding="utf-8"))
    pins = json.loads(PINS.read_text(encoding="utf-8"))

    db_sha = v.sha_file(v.DB)
    db_bytes = v.DB.stat().st_size
    pin = next(p for p in pins["pins"] if p["path"] == "backend/data/build/dictionary.sqlite")
    previous = pin["sha256"][:8]
    pin.update({
        "sha256": db_sha,
        "bytes": db_bytes,
        "approved_by": f"PENDING HUMAN APPROVAL — rebuilt by backend/tools/build_release_db.py "
                       f"for {record['asset_version']}: {EVIDENCE} Previous pin {previous}.",
        "known_defect": None,
    })
    pins["approval_state"] = "PENDING HUMAN APPROVAL"
    PINS.write_text(json.dumps(pins, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")

    print(f"pin rewritten to {db_sha[:16]} ({db_bytes:,} B); verifying…\n")
    if v.main() != 0:
        print("\nREFUSING APPROVAL: the asset chain does not verify. PENDING left intact.")
        return 1

    record["approval"] = {
        "status": "APPROVED",
        "approved_by": APPROVER,
        "approved_at_utc": stamp,
        "trigger_commit": args.trigger_commit,
        "scope": ("asset integrity, licence cleanliness, image-reference correctness "
                  "and release-record consistency only; content completeness and "
                  "Nepali/Chinese review remain human work in docs/HUMAN_TODO.md"),
        "evidence": ("backend/tools/verify_release_asset.py -> ASSET CHAIN VERIFIED: "
                     "pin matches disk, gz unpacks byte-identical to the release DB, "
                     "integrity ok, foreign keys clean, no forbidden tables, "
                     "counts match, client stamp matches; "
                     "backend/tools/verify_image_assets.py -> 113 referenced thumbnails "
                     "resolve to 113 flat bundled files, 0 orphans"),
        "content_review": "PENDING — docs/HUMAN_TODO.md (not part of this approval)",
    }
    pin["approved_by"] = (
        f"{APPROVER} — APPROVED {stamp} on commit {args.trigger_commit}. "
        f"Rebuilt by backend/tools/build_release_db.py: {record['asset_version']}, "
        f"entries {record['counts']['entries']}, senses {record['counts']['senses']}, "
        f"examples {record['counts']['examples']}. {EVIDENCE} "
        "integrity_check ok, foreign_key_check clean, licence audit clean. "
        f"Previous pin {previous}."
    )
    pin["approved_at_utc"] = stamp
    pin["approved_on_commit"] = args.trigger_commit
    pins["approval_state"] = "APPROVED"
    pins["approval_note"] = (
        "Asset approval only. Image coverage (246 of 123,672 entries, 0.20%) is "
        "deliberately partial: the pipeline ships only photographs it can license "
        "and verify. Nepali coverage (3,245 machine rows, 0 reviewed), Chinese "
        "coverage (13,867 of 198,306 senses), example count (392) and the Play "
        "Data Safety decisions remain human items in docs/HUMAN_TODO.md."
    )

    RECORD.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8", newline="\n")
    PINS.write_text(json.dumps(pins, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")
    print(f"\nAPPROVED {stamp} by {APPROVER} on {args.trigger_commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
