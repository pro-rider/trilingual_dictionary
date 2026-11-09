"""Quarantine example sentences that are provably wrong.

A sentence is hidden from the app (review_status='quarantined') only on a
mechanical defect, never on a style judgement:

  * Hangul or Cyrillic inside the Chinese line  (imported text leaked)
  * Nepali line written in Latin with no Devanagari  (never translated)
  * empty English or empty Chinese line
  * Chinese line shorter than 4 characters  (truncated import)

Everything else stays as it is and keeps its status label, because "the Nepali
may be awkward" is not something a regex can decide — that needs the review CSV
workflow.

Usage:
  .\.venv\Scripts\python.exe tools\quarantine_examples.py            # report only
  .\.venv\Scripts\python.exe tools\quarantine_examples.py --apply
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from collections import Counter
from pathlib import Path

HANGUL = re.compile(r"[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7AF]")
CYRILLIC = re.compile(r"[\u0400-\u04FF]")
DEVANAGARI = re.compile(r"[\u0900-\u097F]")
LATIN = re.compile(r"[A-Za-z]")


def reasons(en: str, zh: str, ne: str) -> list[str]:
    out = []
    if not en.strip():
        out.append("empty_en")
    if not zh.strip():
        out.append("empty_zh")
    if HANGUL.search(zh):
        out.append("hangul_in_zh")
    if CYRILLIC.search(zh):
        out.append("cyrillic_in_zh")
    if ne.strip() and not DEVANAGARI.search(ne) and LATIN.search(ne):
        out.append("ne_not_devanagari")
    if zh.strip() and len(zh.strip()) < 4:
        out.append("zh_too_short")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/build/dictionary.sqlite")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    rows = con.execute(
        "SELECT example_id, en, zh, ne, review_status FROM examples").fetchall()
    print(f"examples: {len(rows)}")
    tally: Counter = Counter()
    to_quarantine = []
    for eid, en, zh, ne, status in rows:
        why = reasons(en or "", zh or "", ne or "")
        if why:
            tally[",".join(why)] += 1
            to_quarantine.append((eid, ",".join(why)))
        else:
            tally["ok"] += 1

    print("classification:", dict(tally))
    print("would quarantine:", len(to_quarantine))

    if args.apply and to_quarantine:
        for eid, why in to_quarantine:
            con.execute(
                "UPDATE examples SET review_status = 'quarantined' WHERE example_id = ?",
                (eid,))
        con.commit()
        print("quarantined:", len(to_quarantine))
        print("status now:", [tuple(r) for r in con.execute(
            "SELECT review_status, COUNT(*) FROM examples GROUP BY review_status")])

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
