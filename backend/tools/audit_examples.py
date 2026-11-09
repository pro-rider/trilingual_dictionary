"""Audit example sentences: coverage, review status, and content defects."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "build" / "dictionary.sqlite"

HANGUL = re.compile(r"[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7AF]")
LATIN = re.compile(r"[A-Za-z]")
DEVANAGARI = re.compile(r"[\u0900-\u097F]")
CYRILLIC = re.compile(r"[\u0400-\u04FF]")


def main() -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print("examples:", con.execute("SELECT COUNT(*) FROM examples").fetchone()[0])
    print("review_status:", dict(con.execute(
        "SELECT COALESCE(review_status,'<null>'), COUNT(*) FROM examples").groupby)) if False else None
    print("review_status:", [tuple(r) for r in con.execute(
        "SELECT COALESCE(review_status,'<null>') s, COUNT(*) FROM examples GROUP BY s")])

    bad = Counter()
    rows = con.execute("SELECT example_id, en, zh, ne FROM examples").fetchall()
    bad_ids = {"hangul": [], "ne_latin": [], "zh_empty": [], "en_empty": [],
               "cyrillic": []}
    for r in rows:
        if HANGUL.search(r["zh"] or ""):
            bad["hangul"] += 1
            bad_ids["hangul"].append(r["example_id"])
        if r["ne"] and not DEVANAGARI.search(r["ne"]) and LATIN.search(r["ne"]):
            bad["ne_latin"] += 1
            bad_ids["ne_latin"].append(r["example_id"])
        if not (r["zh"] or "").strip():
            bad["zh_empty"] += 1
            bad_ids["zh_empty"].append(r["example_id"])
        if not (r["en"] or "").strip():
            bad["en_empty"] += 1
            bad_ids["en_empty"].append(r["example_id"])
        if CYRILLIC.search(r["zh"] or ""):
            bad["cyrillic"] += 1
            bad_ids["cyrillic"].append(r["example_id"])

    print("defects:", dict(bad))
    for k, v in bad_ids.items():
        print(k, "first ids:", v[:12], "total", len(v))

    # coverage by frequency band of the entry
    print("entries with examples by freq band:", [
        tuple(r) for r in con.execute(
            "SELECT CASE WHEN e.freq_rank IS NULL THEN 'none' "
            "WHEN e.freq_rank<=1000 THEN '<=1k' WHEN e.freq_rank<=5000 THEN '<=5k' "
            "WHEN e.freq_rank<=20000 THEN '<=20k' ELSE '>20k' END b, COUNT(DISTINCT e.entry_id) "
            "FROM entries e JOIN senses s ON s.entry_id=e.entry_id "
            "JOIN examples x ON x.sense_id=s.sense_id GROUP BY b")])

    # a sample of suspicious Nepali rows for review
    sample = con.execute(
        "SELECT example_id, zh, ne FROM examples WHERE ne IS NOT NULL AND ne != '' "
        "LIMIT 5").fetchall()
    print("ne sample:", [(r["example_id"], (r["zh"] or "")[:20], (r["ne"] or "")[:30])
                         for r in sample])
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
