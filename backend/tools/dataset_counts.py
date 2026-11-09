"""Reconcile every number we quote, with its unit and its query.

Each metric states explicitly whether it counts entries, senses, translation
records, HSK words or HSK senses, and prints the SQL it came from, so a number
in a report can always be reproduced instead of trusted.

Writes docs/PHASE2.1-COUNTS.md.
"""
from __future__ import annotations

import os
import sqlite3

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICTIONARY = os.path.join(BACKEND, "data", "build", "dictionary.sqlite")
STORE = os.path.join(BACKEND, "data", "build", "translations.db")
OUT = os.path.join(os.path.dirname(BACKEND), "docs", "PHASE2.1-COUNTS.md")

METRICS = [
    ("entries", "entry", DICTIONARY, "select count(*) from entries"),
    ("entries_with_freq", "entry", DICTIONARY, "select count(*) from entries where freq_rank is not null"),
    ("senses", "sense", DICTIONARY, "select count(*) from senses"),
    ("senses_with_nepali", "sense (translation value in senses.gloss_ne)", DICTIONARY,
     "select count(*) from senses where trim(coalesce(gloss_ne,''))<>''"),
    ("entries_with_nepali", "entry (has >=1 Nepali sense)", DICTIONARY,
     "select count(distinct s.entry_id) from senses s where trim(coalesce(s.gloss_ne,''))<>''"),
    ("senses_nepali_status_ai_translated", "sense (ne_status='ai_translated')", DICTIONARY,
     "select count(*) from senses where ne_status='ai_translated'"),
    ("senses_hsk_entry_total", "sense (belongs to an entry with hsk_level)", DICTIONARY,
     "select count(*) from senses s join entries e on e.entry_id=s.entry_id where e.hsk_level is not null"),
    ("senses_nepali_inside_hsk_entries", "sense (Nepali value, entry has hsk_level)", DICTIONARY,
     "select count(*) from senses s join entries e on e.entry_id=s.entry_id "
     "where e.hsk_level is not null and trim(coalesce(s.gloss_ne,''))<>''"),
    ("entries_hsk_tagged", "entry (hsk_level not null)", DICTIONARY,
     "select count(*) from entries where hsk_level is not null"),
    ("entries_hsk_tagged_with_nepali", "entry (hsk_level not null and has Nepali sense)", DICTIONARY,
     "select count(*) from entries e where e.hsk_level is not null and exists("
     "select 1 from senses s where s.entry_id=e.entry_id and trim(coalesce(s.gloss_ne,''))<>'')"),
    ("examples_total", "example row", DICTIONARY, "select count(*) from examples"),
    ("examples_reviewed", "example row", DICTIONARY,
     "select count(*) from examples where review_status='reviewed'"),
    ("fts_rows", "FTS row (search index, mirrors entries)", DICTIONARY, "select count(*) from fts"),
    ("fts_zh_rows", "FTS row (trigram index, mirrors entries)", DICTIONARY, "select count(*) from fts_zh"),
    ("translations_rows", "translation record (translations.db)", STORE, "select count(*) from translations"),
    ("translations_legacy_imported", "translation record (origin dictionary.sqlite:senses.ne)", STORE,
     "select count(*) from translations where origin_source='dictionary.sqlite:senses.ne'"),
    ("translations_verified", "translation record (human_verification='verified')", STORE,
     "select count(*) from translations where human_verification='verified'"),
    ("evidence_rows", "evidence record", STORE, "select count(*) from evidence"),
    ("id_map_rows", "id_map row (sense_id -> sense_key, one per dictionary build)", STORE,
     "select count(*) from id_map"),
    ("sense_pos_rows", "POS record", STORE, "select count(*) from sense_pos"),
    ("sense_hsk_rows", "HSK record", STORE, "select count(*) from sense_hsk"),
]


def run():
    rows, failures = [], []
    for name, unit, db, sql in METRICS:
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
            try:
                value = conn.execute(sql).fetchone()[0]
            finally:
                conn.close()
        except Exception as exc:                       # a missing table is reported, not hidden
            value = None
            failures.append("%s: %s" % (name, exc))
        rows.append({"metric": name, "value": value, "unit": unit, "db": os.path.basename(db), "sql": sql})
    return rows, failures


def write_markdown(rows, failures):
    lines = [
        "# Dataset counts, with units and queries",
        "",
        "Every number below states its unit and the exact SQL it came from. "
        "Nothing here mixes entries with senses or with translation records.",
        "",
        "| metric | value | unit | database |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append("| `%s` | %s | %s | %s |" % (r["metric"], "—" if r["value"] is None else r["value"],
                                                    r["unit"], r["db"]))
    lines += ["", "## Queries", ""]
    for r in rows:
        lines.append("* `%s` — `%s`" % (r["metric"], r["sql"]))
    if failures:
        lines += ["", "## Missing or failing", ""]
        lines += ["* %s" % f for f in failures]
    lines += [
        "",
        "## How the overlap was calculated",
        "",
        "Overlap is computed on `senses` rows joined to `entries` on `entry_id`; an "
        "entry counts as Nepali-bearing when at least one of its senses has a "
        "non-empty `gloss_ne`. Both sides therefore use the same identity "
        "(`entry_id` from the dictionary, and the derived `entry_key`/`sense_key` "
        "in `translations.db`), never a headword string match.",
        "",
    ]
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    data, problems = run()
    write_markdown(data, problems)
    width = max(len(d["metric"]) for d in data)
    for d in data:
        print("%-*s %10s  %s" % (width, d["metric"], "—" if d["value"] is None else d["value"], d["unit"]))
    print("\nwritten:", OUT)
    if problems:
        print("problems:", problems)
