"""Remove romanisation ruby markup from Wiktionary candidate example text.

The `examples` column of `gloss_zh_wikt_candidates` stores raw wiki template
text. Some of it carries ruby markup such as `红{Âng}尘`, whose diacritics live
inside the braces and trip the strict encoding gate (U+00C2 is a legitimate
Min-nan romanisation, but the gate cannot tell that apart from mojibake).

This tool drops the brace-enclosed romanisation segments (`{...}` containing a
Latin letter) while keeping the Chinese text intact, then reports how many rows
changed. It never invents text: the remaining characters are untouched.

    python tools/clean_wikt_candidate_examples.py --dry-run
    python tools/clean_wikt_candidate_examples.py
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB = REPO_ROOT / "backend" / "data" / "build" / "dictionary.sqlite"

RUBY_LATIN = re.compile(r"\{[^{}]*[A-Za-z\u00C0-\u024F][^{}]*\}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT entry_id, examples FROM gloss_zh_wikt_candidates "
        "WHERE examples IS NOT NULL AND examples != ''"
    ).fetchall()
    changed = []
    for entry_id, text in rows:
        cleaned = RUBY_LATIN.sub("", text)
        if cleaned != text:
            changed.append((entry_id, text, cleaned))

    for entry_id, before, after in changed[:5]:
        print(f"entry_id {entry_id}:")
        print(f"  before: {before[:120]}")
        print(f"  after : {after[:120]}")
    print(f"rows needing cleanup: {len(changed)}")

    if not args.dry_run and changed:
        con.executemany(
            "UPDATE gloss_zh_wikt_candidates SET examples=? WHERE entry_id=?",
            [(after, entry_id) for entry_id, _, after in changed],
        )
        con.commit()
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
