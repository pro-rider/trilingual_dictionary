"""Demote non-lexical senses so sense 0 is the word's real meaning.

CC-CEDICT sometimes lists a surname, an abbreviation, or a variant reading
first, e.g. 水 = ["surname Shui", "Shui ethnic group", "water", ...]. Ranking
by sense order (or by any per-entry heuristic) then opens "water" on the

surname. This rewrites ``senses.sense_order`` per entry so that:

    0..n   real meanings, in their original relative order
    n..    surname / abbr. / variant / archaic / "used in" senses

It is idempotent: running it again changes nothing. ``sense_id`` is untouched,
so examples and Nepali glosses stay attached to the sense they belong to.

    .venv\\Scripts\\python.exe tools/reorder_senses.py --db data\\build\\dictionary.sqlite
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DEMOTE_PREFIXES = (
    "surname ",
    "abbr. for",
    "abbr for",
    "variant of",
    "old variant",
    "used in",
    "(archaic)",
    "archaic",
    "Japanese variant",
    "see ",
    "see also ",
    "name of ",
    "ancient ",
)

DEMOTE_SUFFIXES = (
    " ethnic group",
    " (ethnic group)",
    " (surname)",
)

# Commercial senses sit next to the everyday word (苹果 lists "Apple (American
# tech company)" before the fruit), so "apple" opened on the company.
DEMOTE_CONTAINS = (
    "company)",
    " inc.",
    " corporation)",
)


def is_nonlexical(gloss: str) -> bool:
    text = (gloss or "").strip().lower()
    if any(text.startswith(p) for p in DEMOTE_PREFIXES):
        return True
    if any(text.endswith(s) for s in DEMOTE_SUFFIXES):
        return True
    return any(c in text for c in DEMOTE_CONTAINS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/build/dictionary.sqlite")
    args = ap.parse_args()

    path = Path(args.db)
    if not path.exists():
        print(f"missing database: {path}")
        return 1

    con = sqlite3.connect(path)
    cur = con.cursor()

    entries = [r[0] for r in cur.execute("SELECT entry_id FROM entries")]
    moved = 0
    reordered_entries = 0

    for entry_id in entries:
        senses = cur.execute(
            "SELECT sense_id, sense_order, gloss_en FROM senses "
            "WHERE entry_id = ? ORDER BY sense_order", (entry_id,)
        ).fetchall()
        if len(senses) < 2:
            continue
        lexical = [s for s in senses if not is_nonlexical(s[2])]
        nonlex = [s for s in senses if is_nonlexical(s[2])]
        ordered = lexical + nonlex
        if [s[0] for s in ordered] == [s[0] for s in senses]:
            continue
        # Move everything to a temporary negative range first so the
        # (entry_id, sense_order) unique constraint cannot collide mid-shuffle.
        for i, (sense_id, _old, _g) in enumerate(ordered):
            cur.execute(
                "UPDATE senses SET sense_order = ? WHERE sense_id = ?",
                (-1 - i, sense_id))
        for i, (sense_id, _old, _g) in enumerate(ordered):
            cur.execute(
                "UPDATE senses SET sense_order = ? WHERE sense_id = ?",
                (i, sense_id))
        reordered_entries += 1
        moved += len(nonlex)

    con.commit()
    print(f"reordered entries: {reordered_entries}, senses demoted: {moved}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
