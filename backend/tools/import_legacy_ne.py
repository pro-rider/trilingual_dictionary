"""Import the existing Nepali glosses from dictionary.sqlite into translations.db.

Data ownership this implements (also documented in docs/PHASE2.1-CORRECTIONS.md):

* ``dictionary.sqlite.senses.gloss_ne`` stays the authoritative original source.
  This tool opens it ``mode=ro`` and never writes to it.
* ``translations.db`` becomes the governance store. Every legacy value is
  imported once, tagged with an import batch, so governance (labels, quarantine,
  corrections, human verification) can act on it without editing the dictionary.
* The original ``sense_id`` is kept in ``origin_record_id`` and mirrored into
  ``id_map`` so a row can always be traced back to its dictionary sense.
* Duplicates are refused by ``(sense_key, origin_source, origin_record_id)``.
* The whole import is reversible: ``--rollback-batch`` deletes exactly the rows
  of one batch and leaves the dictionary untouched.

``ne_status = 'ai_translated'`` is the only provenance marker the dictionary
keeps. Per DATA-GOVERNANCE.md it was written by ``tools/enrich_dictionary.py``
and is explicitly never ``reviewed``. So the import records
``generation_method = 'llm'`` with model, prompt, evidence and validation left
unknown — the flag proves machine generation, nothing more.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.translations import schema  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICTIONARY = os.path.join(BACKEND, "data", "build", "dictionary.sqlite")
STORE = os.path.join(BACKEND, "data", "build", "translations.db")

ORIGIN_SOURCE = "dictionary.sqlite:senses.ne"
ORIGIN_METHOD = "legacy_ai_import"


def read_dictionary(path):
    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    try:
        meta = dict(conn.execute("select key, value from meta").fetchall())
        rows = conn.execute(
            """
            select s.sense_id, s.entry_id, e.simplified, e.pinyin_plain, s.gloss_en,
                   s.gloss_ne, s.ne_status, s.source_id
            from senses s join entries e on e.entry_id = s.entry_id
            where trim(coalesce(s.gloss_ne, '')) <> ''
            order by s.sense_id
            """
        ).fetchall()
    finally:
        conn.close()
    return meta, rows


def plan(rows, data_version):
    planned, skipped, problems = [], [], []
    seen = set()
    for sense_id, entry_id, simplified, pinyin, gloss_en, gloss_ne, ne_status, source_id in rows:
        if not (simplified and pinyin and gloss_en):
            problems.append({"sense_id": sense_id, "why": "missing key component"})
            continue
        key = schema.sense_key(simplified, pinyin, gloss_en)
        ekey = schema.entry_key(simplified, pinyin)
        dedupe = (key, ORIGIN_SOURCE, str(sense_id))
        if dedupe in seen:
            skipped.append({"sense_id": sense_id, "why": "duplicate in source selection"})
            continue
        seen.add(dedupe)
        planned.append({
            "translation_id": None,
            "sense_key": key,
            "entry_key": ekey,
            "language": "ne",
            "text": gloss_ne,
            "generation_method": "llm",
            "evidence_strength": "none",
            "validation_status": "incomplete",
            "publication_status": "labeled",
            "human_verification": "not_verified",
            "origin_source": ORIGIN_SOURCE,
            "origin_record_id": str(sense_id),
            "origin_retrieved_at": schema.utc_now(),
            "origin_method": ORIGIN_METHOD,
            "origin_source_version": data_version,
            "legacy_status": None,
            "import_batch": None,          # filled in by apply()
            "evidence_ids": json.dumps([]),
            "flags": json.dumps([]),
            "created_at": schema.utc_now(),
            "entry_id": entry_id,
            "data_version": data_version,
        })
    return planned, skipped, problems


INSERT_SQL = """
insert into translations(
    sense_key, entry_key, language, text, generation_method, evidence_strength,
    validation_status, publication_status, human_verification,
    origin_source, origin_record_id, origin_retrieved_at, origin_method,
    origin_source_version, legacy_status, import_batch, evidence_ids, flags,
    created_at)
values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def apply(rows, store, data_version, batch, fail_after=None):
    """Insert the batch in one transaction.

    ``BEGIN IMMEDIATE`` takes the write lock up front, so a concurrent writer
    cannot interleave and leave a half-imported batch. Everything the batch owns
    — translation rows, ``id_map``, ``event_log``, the ``versions`` marker — is
    inside that single transaction; any failure rolls all of it back.

    ``fail_after`` exists only for failure-injection tests: it raises after that
    many inserts so the rollback path can be proven on real code.
    """
    conn = schema.connect(store)
    conn.isolation_level = None                     # explicit transaction control
    try:
        existing = {
            (r[0], r[1], r[2])
            for r in conn.execute(
                "select sense_key, origin_source, origin_record_id from translations "
                "where origin_source = ?", (ORIGIN_SOURCE,))
        }
        inserted, duplicates = 0, 0
        conn.execute("BEGIN IMMEDIATE")
        try:
            for row in rows:
                if (row["sense_key"], ORIGIN_SOURCE, row["origin_record_id"]) in existing:
                    duplicates += 1
                    continue
                if fail_after is not None and inserted >= fail_after:
                    raise RuntimeError("injected failure after %d rows" % inserted)
                conn.execute(INSERT_SQL, (
                    row["sense_key"], row["entry_key"], row["language"], row["text"],
                    row["generation_method"], row["evidence_strength"],
                    row["validation_status"], row["publication_status"],
                    row["human_verification"], row["origin_source"],
                    row["origin_record_id"], row["origin_retrieved_at"],
                    row["origin_method"], row["origin_source_version"],
                    row["legacy_status"], batch, row["evidence_ids"], row["flags"],
                    row["created_at"],
                ))
                tid = conn.execute("select last_insert_rowid()").fetchone()[0]
                conn.execute(
                    "insert or replace into id_map(entry_id, entry_key, sense_id, sense_key, data_version) "
                    "values(?,?,?,?,?)",
                    (row["entry_id"], row["entry_key"], int(row["origin_record_id"]),
                     row["sense_key"], row["data_version"]),
                )
                conn.execute(
                    "insert into event_log(occurred_at, actor, action, table_name, record_key, "
                    "after_json, note) values(?,?,?,?,?,?,?)",
                    (schema.utc_now(), "import_legacy_ne", "legacy_ne_imported", "translations",
                     str(tid), json.dumps({"batch": batch, "sense_id": row["origin_record_id"],
                                           "sense_key": row["sense_key"]}, ensure_ascii=False),
                     "imported from dictionary.sqlite, original dictionary untouched"),
                )
                inserted += 1
            conn.execute(
                "insert or ignore into versions(component, version, note, created_at) "
                "values('import', ?, 'legacy Nepali import batch', ?)",
                (batch, schema.utc_now()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return {"batch": batch, "inserted": inserted, "duplicates_skipped": duplicates}


def verify(store, dictionary, batch=None):
    """Compare imported rows against the dictionary, value by value."""
    conn = schema.connect(store)
    try:
        where = "where import_batch = ?" if batch else ""
        args = (batch,) if batch else ()
        imported = conn.execute(
            "select origin_record_id, text, sense_key, entry_key from translations "
            "where origin_source = ? %s" % (" and import_batch = ?" if batch else ""),
            (ORIGIN_SOURCE,) + args,
        ).fetchall()
        total_in_store = conn.execute(
            "select count(*) from translations where origin_source = ?", (ORIGIN_SOURCE,)
        ).fetchone()[0]
        fk = len(conn.execute("pragma foreign_key_check").fetchall())
        integrity = conn.execute("pragma quick_check").fetchone()[0]
        ids = {}
        for r in conn.execute("select sense_id, sense_key, entry_key from id_map"):
            ids[r[0]] = (r[1], r[2])
    finally:
        conn.close()

    meta, rows = read_dictionary(dictionary)
    # row order: sense_id, entry_id, simplified, pinyin_plain, gloss_en, gloss_ne, ...
    source = {str(r[0]): (schema.sense_key(r[2], r[3], r[4]), schema.entry_key(r[2], r[3]), r[5])
              for r in rows}

    missing, text_mismatch, key_mismatch, extra = [], [], [], []
    for sid, text, skey, ekey in imported:
        if sid not in source:
            extra.append(sid)
            continue
        exp_key, exp_ekey, exp_text = source[sid]
        if text != exp_text:
            text_mismatch.append({"sense_id": sid, "store": text, "dictionary": exp_text})
        if skey != exp_key or ekey != exp_ekey:
            key_mismatch.append({"sense_id": sid, "store": [skey, ekey], "expected": [exp_key, exp_ekey]})
    imported_ids = {sid for sid, _t, _s, _e in imported}
    for sid in source:
        if sid not in imported_ids:
            missing.append(sid)

    return {
        "dictionary_rows_with_ne": len(rows),
        "store_rows_for_origin": total_in_store,
        "imported_rows_checked": len(imported),
        "missing_vs_dictionary": len(missing),
        "text_mismatches": len(text_mismatch),
        "key_mismatches": len(key_mismatch),
        "unknown_sense_ids": len(extra),
        "id_map_rows": len(ids),
        "foreign_key_violations": fk,
        "integrity": integrity,
        "data_version": meta.get("dataset_version"),
        "built_at": meta.get("built_at"),
        "sample_mismatches": (text_mismatch + key_mismatch)[:5],
        "missing_sample": missing[:5],
        "ok": (len(missing) == 0 and not text_mismatch and not key_mismatch and not extra
               and fk == 0 and integrity == "ok"),
    }


def rollback_batch(store, batch):
    """Remove one batch's translation rows, keeping the audit trail.

    The rows go; the ``event_log`` entries that recorded the import stay, and an
    explicit ``rollback_import_batch`` event is written in the same transaction.
    ``id_map`` is kept too — it maps dictionary sense ids to stable keys and is
    not a claim that a translation row exists. That keeps "what was imported,
    when, and that it was withdrawn" answerable after the rows are gone.
    """
    conn = schema.connect(store)
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = conn.execute(
                "select count(*) from translations where import_batch = ?", (batch,)).fetchone()[0]
            conn.execute("delete from translations where import_batch = ?", (batch,))
            conn.execute(
                "insert into event_log(occurred_at, actor, action, table_name, record_key, note) "
                "values(?,?,?,?,?,?)",
                (schema.utc_now(), "import_legacy_ne", "rollback_import_batch", "translations",
                 batch, "removed %d imported rows; dictionary.sqlite untouched; audit rows kept" % rows),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return {"batch": batch, "deleted": rows, "dictionary_untouched": True,
            "audit_preserved": True}


def main():
    ap = argparse.ArgumentParser(description="Import legacy Nepali glosses into translations.db")
    ap.add_argument("--dictionary", default=DICTIONARY)
    ap.add_argument("--store", default=STORE)
    ap.add_argument("--apply", action="store_true", help="write the import (default: dry run)")
    ap.add_argument("--verify", action="store_true", help="compare store against the dictionary")
    ap.add_argument("--rollback-batch", metavar="BATCH")
    ap.add_argument("--batch", help="batch id (default: legacy-ne-<UTC stamp>)")
    ap.add_argument("--report", help="write the JSON report here")
    args = ap.parse_args()

    if args.rollback_batch:
        print(json.dumps(rollback_batch(args.store, args.rollback_batch), indent=2))
        return

    if args.verify:
        print(json.dumps(verify(args.store, args.dictionary), indent=2))
        return

    meta, rows = read_dictionary(args.dictionary)
    data_version = "dictionary-%s@%s" % (meta.get("dataset_version"), meta.get("built_at"))
    batch = args.batch or ("legacy-ne-%s" % schema.utc_stamp())
    planned, skipped, problems = plan(rows, data_version)

    report = {
        "mode": "apply" if args.apply else "dry-run",
        "dictionary": args.dictionary,
        "store": args.store,
        "dictionary_dataset_version": meta.get("dataset_version"),
        "dictionary_built_at": meta.get("built_at"),
        "ne_status_values": dict(),
        "rows_planned": len(planned),
        "rows_skipped": skipped,
        "rows_rejected": problems,
        "batch": batch,
    }
    conn = sqlite3.connect("file:%s?mode=ro" % args.dictionary.replace("\\", "/"), uri=True)
    report["ne_status_values"] = dict(conn.execute(
        "select ne_status, count(*) from senses where trim(coalesce(gloss_ne,''))<>'' group by 1"
    ).fetchall())
    conn.close()

    if args.apply:
        if not os.path.exists(args.store):
            report["error"] = "store missing; run tools/migrate_translations.py first"
            print(json.dumps(report, indent=2))
            raise SystemExit(1)
        report["apply"] = apply(planned, args.store, data_version, batch)
        report["verify"] = verify(args.store, args.dictionary, batch)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
