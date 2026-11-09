"""Verify or rebuild the FTS5 search indexes that live inside dictionary.sqlite.

Search is served from two virtual tables inside the shipped database:

* ``fts``    — fts5(simplified, traditional, pinyin_search, english, category,
                entry_id UNINDEXED), tokenize unicode61
* ``fts_zh`` — fts5(simplified, traditional, english, entry_id UNINDEXED),
                tokenize trigram

Both mirror ``entries``. They are therefore invalidated by any rebuild or data
change of ``entries``, which is why ``tools/build_dictionary.py`` must rebuild
them at build time. This tool is the verification half: it compares index sizes
against the base table, checks a known row is findable, and can rebuild on a
copy.

Default is verify-only, and it opens the database read-only. ``--rebuild``
must be pointed at a database you are allowed to change (a freshly built asset or
a scratch copy), never at the source of truth unless you mean it.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(BACKEND, "data", "build", "dictionary.sqlite")

BASE_COLUMNS = {
    "fts": ("simplified", "traditional", "pinyin_search", "english", "category", "entry_id"),
    "fts_zh": ("simplified", "traditional", "english", "entry_id"),
}


def _connect(path, readonly):
    if readonly:
        return sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    return sqlite3.connect(path)


def verify(path):
    conn = _connect(path, readonly=True)
    try:
        probes = []
        entries = conn.execute("select count(*) from entries").fetchone()[0]
        for table, columns in BASE_COLUMNS.items():
            rows = conn.execute("select count(*) from %s" % table).fetchone()[0]
            # A word that must be findable, chosen deterministically.
            sample = conn.execute(
                "select simplified from entries where freq_rank is not null "
                "order by freq_rank limit 1").fetchone()[0]
            select = ", ".join("null" if c == "entry_id" else c for c in columns)
            hit = conn.execute(
                "select count(*) from %s where %s match ?" % (table, "simplified"), (sample,)).fetchone()[0]
            probes.append({
                "table": table,
                "indexed_rows": rows,
                "base_entries": entries,
                "rows_match_entries": rows == entries,
                "sample_word": sample,
                "sample_found": hit > 0,
                "columns": list(columns),
            })
        integrity = conn.execute("pragma quick_check").fetchone()[0]
        return {"database": path, "entries": entries, "probes": probes,
                "integrity": integrity,
                "ok": all(p["rows_match_entries"] and p["sample_found"] for p in probes)
                      and integrity == "ok"}
    finally:
        conn.close()


def rebuild(path):
    conn = sqlite3.connect(path)
    try:
        with conn:
            for table, columns in BASE_COLUMNS.items():
                conn.execute("insert into %s(%s) values('delete-all')" % (table, table))
                conn.execute(
                    "insert into %s(%s) select %s from entries" % (table, ", ".join(columns),
                                                                   ", ".join(columns)))
    finally:
        conn.close()
    return verify(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--rebuild", action="store_true",
                    help="rebuild both FTS5 indexes from entries (use a copy or a fresh build)")
    args = ap.parse_args()
    result = rebuild(args.db) if args.rebuild else verify(args.db)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
