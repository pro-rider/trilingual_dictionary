"""Repair gloss columns in exported CSVs using the database as the single truth.

The exports drifted from the database: ``vocabulary_table_clean.csv`` has 7,889
rows whose ``gloss_en`` is empty and 123 rows whose gloss disagrees with the
database, and ``vocabulary_table2_clean.csv`` has no English gloss at all. Those
cells are *missing or stale*, not mistranslated, so the fix is a deterministic
join — never a generated guess.

Two outputs per file:

* ``<name>_repaired.csv`` — empty cells filled from the database; original columns
  and row order kept.
* ``<name>_conflicts.csv`` — rows where the CSV and the database disagree. Both
  values are reported and **nothing is overwritten**: a conflict means one of the
  two sources is wrong, and that is a human decision, not a script's.

Usage:
    python tools/repair_gloss_csv.py data\\words.csv data\\vocabulary.csv --out-dir data/build/repaired
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import Counter
from pathlib import Path

GLOSS_COLUMNS = ("gloss_en", "gloss_zh", "gloss_ne")


def load_database(db_path: Path) -> dict[str, dict[str, str]]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    mapping: dict[str, dict[str, str]] = {}
    for word, en, zh, ne in con.execute(
        """
        SELECT e.simplified, s.gloss_en, s.gloss_zh, s.gloss_ne
        FROM entries e JOIN senses s ON s.entry_id = e.entry_id AND s.sense_order = 0
        """
    ):
        mapping[word] = {"gloss_en": en or "", "gloss_zh": zh or "", "gloss_ne": ne or ""}
    con.close()
    return mapping


def repair(path: Path, mapping: dict[str, dict[str, str]], out_dir: Path) -> None:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    filled = Counter()
    conflicts: list[dict[str, str]] = []
    unmatched = 0

    for row in rows:
        word = (row.get("word") or row.get("simplified") or "").strip()
        truth = mapping.get(word)
        if not truth:
            unmatched += 1
            continue
        for column in GLOSS_COLUMNS:
            if column not in row:
                continue
            current = (row.get(column) or "").strip()
            correct = (truth.get(column) or "").strip()
            if not current and correct:
                row[column] = correct
                filled[column] += 1
            elif current and correct and current != correct:
                conflicts.append({
                    "file": path.name,
                    "word": word,
                    "column": column,
                    "csv_value": current,
                    "database_value": correct,
                })

    out_dir.mkdir(parents=True, exist_ok=True)
    repaired_path = out_dir / f"{path.stem}_repaired.csv"
    with repaired_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    conflicts_path = out_dir / f"{path.stem}_conflicts.csv"
    with conflicts_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file", "word", "column", "csv_value", "database_value"])
        writer.writeheader()
        writer.writerows(conflicts)

    print(f"{path.name:<32} rows={len(rows):>7} filled={dict(filled)} "
          f"conflicts={len(conflicts)} unmatched={unmatched}")
    print(f"  -> {repaired_path}")
    print(f"  -> {conflicts_path}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--db", type=Path, default=Path("data/build/dictionary.sqlite"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/build/repaired"))
    args = parser.parse_args(argv[1:])

    mapping = load_database(args.db)
    for path in args.files:
        repair(path, mapping, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
