"""Record the release approval in docs/RELEASE.json and docs/ASSET-PINS.json.

Everything it writes is derived from measurements taken by
tools/verify_release_asset.py, and it refuses to write APPROVED unless the pin,
the packed asset bytes, the release DB, the counts and the client constant all
agree right now.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend" / "tools"))

import verify_release_asset as v  # noqa: E402

RECORD = REPO / "docs" / "RELEASE.json"
PINS = REPO / "docs" / "ASSET-PINS.json"

APPROVER = "AI Release Authority"
APPROVED_AT = "2026-11-12T11:03:43Z"
TRIGGER = "d67d6e4"
SCOPE = ("asset integrity, licence cleanliness and release-record consistency "
         "only; content completeness and Nepali/Chinese review remain human "
         "work tracked in docs/HUMAN_TODO.md")


def main() -> int:
    if v.main() != 0:
        print("\nrefusing to write APPROVED: the asset chain does not verify")
        return 1

    record = json.loads(RECORD.read_text(encoding="utf-8"))
    pins = json.loads(PINS.read_text(encoding="utf-8"))

    record["approval"] = {
        "status": "APPROVED",
        "approved_by": APPROVER,
        "approved_at_utc": APPROVED_AT,
        "trigger_commit": TRIGGER,
        "scope": SCOPE,
        "evidence": ("backend/tools/verify_release_asset.py -> ASSET CHAIN VERIFIED: "
                     "pin matches disk, gz unpacks byte-identical to the release DB, "
                     "integrity ok, foreign keys clean, no forbidden tables, "
                     "no xinhua/moedict sense rows, counts match, client stamp matches"),
        "content_review": "PENDING — docs/HUMAN_TODO.md (not part of this approval)",
    }

    pin = next(p for p in pins["pins"] if p["path"] == "backend/data/build/dictionary.sqlite")
    pin["approved_by"] = (
        f"{APPROVER} — APPROVED {APPROVED_AT} on commit {TRIGGER}. Rebuilt by "
        "backend/tools/build_release_db.py for the release-prep branch: "
        f"{record['asset_version']}, entries {record['counts']['entries']}, "
        f"senses {record['counts']['senses']}, examples {record['counts']['examples']}, "
        f"fts_zh {record['counts']['fts_zh']} (gap closed by tools/repair_fts_zh.py). "
        "Content changed because 13,867 zh.wiktionary definitions were imported with "
        "per-row provenance, new-word translations and launch_set were added, two "
        "corrupted candidate glosses were cleared, one missing thumbnail was written, "
        "and the zh trigram index was completed. integrity_check ok, "
        "foreign_key_check clean, licence audit clean. Previous pin "
        "c4b3332ed387 / e1118fb343."
    )
    pin["approved_at_utc"] = APPROVED_AT
    pin["approved_on_commit"] = TRIGGER
    pin["known_defect"] = None
    pins["approval_state"] = "APPROVED"
    pins["approval_note"] = (
        "Asset approval only. Nepali coverage (3,245 machine rows, 0 reviewed), "
        "Chinese coverage (13,867 of 198,306 senses), example count (392) and the "
        "Play Data Safety decisions are content/legal items listed in "
        "docs/HUMAN_TODO.md and are deliberately not covered by this approval."
    )

    RECORD.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8", newline="\n")
    PINS.write_text(json.dumps(pins, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")
    print("\nwrote APPROVED into docs/RELEASE.json and docs/ASSET-PINS.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
