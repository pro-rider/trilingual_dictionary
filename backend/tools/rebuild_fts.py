"""Verify or rebuild the FTS5 search indexes that live inside dictionary.sqlite.

Search is served from two virtual tables inside the shipped database:

* ``fts``    — fts5(simplified, traditional, pinyin_search, english, category,
                entry_id UNINDEXED), tokenize unicode61
* ``fts_zh`` — fts5(simplified, traditional, english, entry_id UNINDEXED),
                tokenize trigram

Both mirror ``entries``, so any change to ``entries`` invalidates them. Validation
is delegated to ``tools/validate_fts.py`` — one exact-ID check, not two.

Default is verify only, read-only, and it exits nonzero when the index set does
not match ``entries``. ``--rebuild`` writes, so it refuses to touch the canonical
asset unless ``--force-source`` is passed; use it on a fresh build or a copy.
Rebuild is deterministic: it deletes every index row and re-inserts from
``entries`` inside one transaction, so running it twice on the same data yields
the same index.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_fts  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(BACKEND, "data", "build", "dictionary.sqlite")

#: `entries` carries no English column: the glosses live in `senses`, one row per
#: meaning. Both indexes index the entry's glosses joined by a space, in sense
#: order, which is exactly what `build_dictionary.py` writes at build time.
ENGLISH = ("(select group_concat(gloss_en, ' ') from "
           "(select gloss_en from senses where senses.entry_id = entries.entry_id "
           "order by sense_order))")

COLUMNS = {
    "fts": ("simplified", "traditional", "pinyin_search", "english", "category", "entry_id"),
    "fts_zh": ("simplified", "traditional", "english", "entry_id"),
}
SELECT = {
    "fts": ("simplified", "traditional", "pinyin_search", ENGLISH, "category", "entry_id"),
    "fts_zh": ("simplified", "traditional", ENGLISH, "entry_id"),
}


def verify(path):
    return validate_fts.check(path)


def rebuild(path):
    """Recreate both indexes from ``entries``; then prove the id sets match."""
    conn = sqlite3.connect(path)
    try:
        with conn:
            for table in COLUMNS:
                conn.execute("delete from %s" % table)
                conn.execute(
                    "insert into %s(%s) select %s from entries"
                    % (table, ", ".join(COLUMNS[table]), ", ".join(SELECT[table])))
    finally:
        conn.close()
    report = validate_fts.check(path)
    report["rebuilt"] = True
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--rebuild", action="store_true",
                    help="rebuild both FTS5 indexes from entries (use a copy or a fresh build)")
    ap.add_argument("--force-source", action="store_true",
                    help="allow --rebuild on the canonical data/build/dictionary.sqlite")
    args = ap.parse_args()

    if args.rebuild:
        same = os.path.normcase(os.path.abspath(args.db)) == os.path.normcase(os.path.abspath(DEFAULT_DB))
        if same and not args.force_source:
            print("refusing to rebuild the canonical asset in place; "
                  "run on a copy or pass --force-source", file=sys.stderr)
            return 2
        result = rebuild(args.db)
    else:
        result = verify(args.db)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["ok"]:
        print("FTS validation FAILED: %s" % "; ".join(result["failures"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
