"""Find and quarantine machine-written text that contains U+FFFD.

The Phase 3 batch run wrote a few Nepali glosses containing the Unicode
replacement character (U+FFFD): the model's output was truncated mid-byte and
Python decoded it as "�". A row like that must never reach a reviewer as if it
were usable text, so this tool:

1. scans the AI-generated candidate columns for U+FFFD,
2. clears the corrupted field and sets the row back to ``pending_gloss`` (or
   ``pending_review`` for examples),
3. prints exactly what it changed.

It touches only candidate tables. ``senses`` and ``examples`` are never modified.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BAD = "\ufffd"

# table, text columns, status column, value to restore
TARGETS = [
    ("words3000_candidates", ["gloss_en", "gloss_zh", "gloss_ne"],
     "status", "pending_gloss"),
    ("example_candidates", ["zh", "en", "ne"], "status", "pending_review"),
]

# Devanagari-only columns that must not contain Latin letters. A model wrote
# "सामuh अधिकार घर" for 共有产权房 — half Devanagari, half transliteration. The
# strict encoding gate flags it as a warning; a reviewer should never see it, so
# the row is reset here exactly like a U+FFFD row.
LATIN_FREE = [("words3000_candidates", "gloss_ne", "status", "pending_gloss"),
              ("example_candidates", "ne", "status", "pending_review")]


def scan(con: sqlite3.Connection, table: str, columns: list[str]) -> list[tuple]:
    hits = []
    for column in columns:
        try:
            rows = con.execute(
                f"SELECT rowid, * FROM {table} WHERE {column} LIKE ?",
                (f"%{BAD}%",),
            ).fetchall()
        except sqlite3.OperationalError:
            continue  # table or column absent in this build
        for row in rows:
            hits.append((table, column, row["rowid"] if hasattr(row, "keys") else row[0]))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/build/dictionary.sqlite")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    db = Path(args.db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    total = 0
    for table, columns, status_col, reset_to in TARGETS:
        hits = scan(con, table, columns)
        if not hits:
            print(f"{table}: clean")
            continue
        print(f"{table}: {len(hits)} corrupted cell(s)")
        by_row: dict[int, list[str]] = {}
        for _, column, rowid in hits:
            by_row.setdefault(rowid, []).append(column)
        if args.dry_run:
            for rowid, cols in list(by_row.items())[:20]:
                word = con.execute(
                    f"SELECT * FROM {table} WHERE rowid = ?", (rowid,)
                ).fetchone()
                label = word[0] if word else rowid
                print(f"   rowid {rowid} ({label}) -> {cols}")
        else:
            for rowid, cols in by_row.items():
                sets = ", ".join(f"{c} = ''" for c in cols)
                con.execute(
                    f"UPDATE {table} SET {sets}, {status_col} = ? "
                    f"WHERE rowid = ?",
                    (reset_to, rowid),
                )
            con.commit()
            print(f"   reset {len(by_row)} row(s) to {reset_to}, fields cleared")
        total += len(hits)

    con.close()
    print(f"total corrupted cells: {total}")

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    total_latin = 0
    for table, column, status_col, reset_to in LATIN_FREE:
        try:
            rows = con.execute(f"SELECT rowid, * FROM {table}").fetchall()
        except sqlite3.OperationalError:
            continue
        bad = [r[0] for r in rows
               if any(ch.isascii() and ch.isalpha() for ch in (r[column] or ""))]
        if not bad:
            print(f"{table}.{column}: no Latin letters")
            continue
        print(f"{table}.{column}: {len(bad)} cell(s) with Latin letters")
        if args.dry_run:
            for rowid in bad[:20]:
                print(f"   rowid {rowid}: {con.execute(f'SELECT * FROM {table} WHERE rowid=?', (rowid,)).fetchone()[column]!r}")
        else:
            for rowid in bad:
                con.execute(
                    f"UPDATE {table} SET {column} = '', {status_col} = ? "
                    f"WHERE rowid = ?", (reset_to, rowid))
            con.commit()
            print(f"   reset {len(bad)} row(s) to {reset_to}")
        total_latin += len(bad)
    con.close()
    print(f"total non-Devanagari cells: {total_latin}")
    return 0 if (total == 0 and total_latin == 0) or not args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
