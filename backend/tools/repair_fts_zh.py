"""Repair the fts_zh gap.

The zh trigram index was built before 76 AI-generated entries were added, so
those headwords are invisible to Chinese full-text search. This tool re-adds
exactly the missing rows — nothing else — and verifies the counts afterwards.

    python tools/repair_fts_zh.py --dry-run
    python tools/repair_fts_zh.py
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DB = BACKEND / "data" / "build" / "dictionary.sqlite"


def english_of(con: sqlite3.Connection, entry_id: int) -> str:
    rows = con.execute(
        "SELECT gloss_en FROM senses WHERE entry_id=? ORDER BY sense_order LIMIT 6",
        (entry_id,),
    ).fetchall()
    return " | ".join(r[0] for r in rows if r[0])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    entries = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    indexed = con.execute("SELECT COUNT(*) FROM fts_zh").fetchone()[0]
    missing = con.execute(
        "SELECT entry_id, simplified, traditional FROM entries "
        "WHERE entry_id NOT IN (SELECT entry_id FROM fts_zh) ORDER BY entry_id"
    ).fetchall()
    print(f"entries {entries:,}  fts_zh {indexed:,}  missing {len(missing):,}")
    if missing:
        print(f"id range {missing[0][0]}..{missing[-1][0]}")

    if args.dry_run:
        for entry_id, simplified, traditional in missing[:5]:
            print(f"  would add {entry_id}: {simplified} / {traditional}")
        print("dry run: nothing written")
        return 0

    for entry_id, simplified, traditional in missing:
        con.execute(
            "INSERT INTO fts_zh (simplified, traditional, english, entry_id) "
            "VALUES (?,?,?,?)",
            (simplified, traditional, english_of(con, entry_id), entry_id),
        )
    con.commit()

    indexed = con.execute("SELECT COUNT(*) FROM fts_zh").fetchone()[0]
    still_missing = con.execute(
        "SELECT COUNT(*) FROM entries WHERE entry_id NOT IN (SELECT entry_id FROM fts_zh)"
    ).fetchone()[0]
    con.close()
    print(f"after  entries {entries:,}  fts_zh {indexed:,}  missing {still_missing:,}")
    if indexed != entries or still_missing:
        print("FAIL: the index still does not cover every entry")
        return 1
    print("OK: every entry is indexed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
