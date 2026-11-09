"""Investigation only: classify Nepali values that contain non-Devanagari letters.

Reads ``dictionary.sqlite`` through a read-only URI. It never writes, never
touches a quarantine table, and never changes a shipped asset — its whole output
is a classification report for a human decision.

    python tools/classify_script_mix.py --db data/build/dictionary.sqlite
    python tools/classify_script_mix.py --db ... --limit 20 --json out.json

The rule and its consequences live in ``app/translations/script_mix.py``.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.translations import script_mix  # noqa: E402

SUSPECT_SQL = """
select s.sense_id, s.entry_id, e.simplified, e.pinyin_plain, s.gloss_en, s.gloss_ne
from senses s join entries e on e.entry_id = s.entry_id
where trim(coalesce(s.gloss_ne, '')) <> ''
  and (
    s.gloss_ne glob '*[A-Za-z]*'
    or s.gloss_ne glob '*[а-яА-Я]*'
  )
order by s.sense_id
"""


def scan(db, limit=None, values=None):
    """Classify suspects. ``values`` replaces the database scan (for tests)."""
    items = []
    if values is not None:
        items = [{"sense_id": None, "simplified": None, "gloss_ne": v} for v in values]
    else:
        if not os.path.exists(db):
            raise SystemExit("dictionary not found: %s" % db)
        conn = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
        try:
            rows = conn.execute(SUSPECT_SQL).fetchall()
        finally:
            conn.close()
        items = [{"sense_id": r[0], "entry_id": r[1], "simplified": r[2],
                  "pinyin": r[3], "gloss_en": r[4], "gloss_ne": r[5]} for r in rows]

    if limit:
        items = items[:limit]

    report = {"scanned": len(items), "by_verdict": {}, "quarantine_candidates": [],
              "kept_visible": [], "escalate": []}
    for item in items:
        verdict = script_mix.classify(item["gloss_ne"])
        key = verdict["verdict"]
        report["by_verdict"][key] = report["by_verdict"].get(key, 0) + 1
        entry = dict(item)
        entry.update(verdict)
        if verdict["quarantine_justified"]:
            report["quarantine_candidates"].append(entry)
        elif key == "foreign_token":
            report["kept_visible"].append(entry)
        elif key in ("no_devanagari", "empty"):
            report["escalate"].append(entry)
    report["note"] = ("classification only — nothing was quarantined or rewritten; "
                      "intra_token_mix is typographic evidence, not proof that the "
                      "Nepali meaning is correct")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(BACKEND, "data", "build", "dictionary.sqlite"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--json", help="write the report here")
    args = ap.parse_args(argv)
    report = scan(args.db, args.limit)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
