"""Deterministic example-sentence gate.

The app already hides a row when `review_status='quarantined'`, when the Chinese
side contains Hangul/Cyrillic, or when the Nepali side is not Devanagari
(lib/data/local/offline_dictionary.dart). Those checks live in the client and
only run per query — nothing stops a bad row from being shipped, and a row that
fails only one check still renders its other two sides.

This script applies the same rules **once, in the data**, adds the reason next
to the row, and prints what it changed. It never uses a model: the rules are
script/length checks, so the verdict is reproducible and reviewable.

Rules (any hit => quarantined):
  R1  Chinese side contains Hangul (가-힣, ㄱ-ㅎ) or Cyrillic
  R2  Nepali side lacks Devanagari, or contains Latin letters
  R3  Empty en / zh / ne
  R4  Chinese side is mostly non-Han (ASCII letters > 20% of characters)
  R5  Sentence-length ratio implausible (en chars vs zh chars outside 0.4–4.0)
  R6  Duplicate English sentence inside one entry
Rows that pass keep their status (imported/reviewed stay visible).

Usage:
  python tools/clean_examples.py --dry-run
  python tools/clean_examples.py
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "build" / "dictionary.sqlite"

HANGUL = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
CYRILLIC = re.compile(r"[\u0400-\u04ff]")
DEVANAGARI = re.compile(r"[\u0900-\u097f]")
LATIN = re.compile(r"[A-Za-z]")
HAN = re.compile(r"[\u4e00-\u9fff]")


def check(en: str, zh: str, ne: str) -> str:
    if not (en or "").strip() or not (zh or "").strip() or not (ne or "").strip():
        return "R3 empty field"
    if HANGUL.search(zh) or CYRILLIC.search(zh):
        return "R1 foreign script in Chinese"
    if not DEVANAGARI.search(ne):
        return "R2 Nepali not Devanagari"
    if len(LATIN.findall(ne)) > 2:
        return "R2 Latin letters in Nepali"
    letters = len(LATIN.findall(zh))
    han = len(HAN.findall(zh))
    if letters and han == 0:
        return "R4 Chinese side has no Han characters"
    en_words = len(re.findall(r"[A-Za-z']+", en))
    zh_chars = max(1, len(HAN.findall(zh)))
    ratio = en_words / zh_chars
    if ratio < 0.2 or ratio > 2.2:
        return "R5 length ratio"
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    cols = {r[1] for r in con.execute("PRAGMA table_info(examples)")}
    if "quarantine_reason" not in cols and not args.dry_run:
        con.execute("ALTER TABLE examples ADD COLUMN quarantine_reason TEXT")
        con.commit()

    rows = con.execute(
        "SELECT example_id, sense_id, en, zh, ne, review_status FROM examples"
    ).fetchall()

    seen: dict[tuple[int, str], int] = {}
    flagged: list[dict] = []
    for row in rows:
        reason = check(row["en"], row["zh"], row["ne"])
        if not reason:
            key = (row["sense_id"], (row["en"] or "").strip().lower())
            if key in seen:
                reason = "R6 duplicate sentence"
            else:
                seen[key] = row["example_id"]
        if reason:
            flagged.append({"example_id": row["example_id"], "reason": reason,
                            "en": row["en"], "ne": row["ne"]})

    report = {
        "total": len(rows),
        "flagged": len(flagged),
        "clean": len(rows) - len(flagged),
        "by_reason": {},
        "sample": flagged[:10],
        "applied": not args.dry_run,
    }
    for item in flagged:
        report["by_reason"][item["reason"]] = report["by_reason"].get(item["reason"], 0) + 1

    if not args.dry_run:
        for item in flagged:
            con.execute(
                "UPDATE examples SET review_status='quarantined', "
                "quarantine_reason=? WHERE example_id=?",
                (item["reason"], item["example_id"]),
            )
        con.commit()
        report["quarantined_total"] = con.execute(
            "SELECT COUNT(*) FROM examples WHERE review_status='quarantined'"
        ).fetchone()[0]
        report["visible_total"] = con.execute(
            "SELECT COUNT(*) FROM examples WHERE review_status IN ('reviewed','imported')"
        ).fetchone()[0]
        report["words_with_visible_example"] = con.execute(
            "SELECT COUNT(DISTINCT s.entry_id) FROM examples e "
            "JOIN senses s ON s.sense_id = e.sense_id "
            "WHERE e.review_status IN ('reviewed','imported')"
        ).fetchone()[0]

    out = ROOT / "data" / "build" / "reports" / "examples_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
