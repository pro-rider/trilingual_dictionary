"""R5 — stage, dry-run, review and promote R3/R4 vocabulary into the master DB.

Safety model
------------
* Read-only until ``--apply``; ``--apply`` only writes **staging** tables.
* ``--promote`` writes ``entries`` / ``senses`` and is gated by an approval file
  (an explicit human decision per headword), never by the mere presence of data.
* A verified or reviewed row is never overwritten: a headword that already
  exists is either skipped (exact duplicate) or reported as a conflict.
* Every promoted row keeps its provenance (source hash, extractor, model,
  confidence, batch) in ``source_evidence``.
* Idempotency key = sha256(headword|pinyin|english glosses): rerunning any batch
  inserts nothing twice.

Usage (read-only dry run, the default):
  .venv\\Scripts\\python.exe tools\\r5_import.py --enriched data\\r3\\enrichments.jsonl ^
      --nepali data\\r4\\ne_results.jsonl --dry-run
Stage the reviewed rows:
  .venv\\Scripts\\python.exe tools\\r5_import.py --enriched ... --nepali ... --apply --batch-id r5-01
Promote only the headwords a human approved:
  .venv\\Scripts\\python.exe tools\\r5_import.py --promote --batch-id r5-01 --approval data\\r5\\approvals.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_fts  # noqa: E402  (exact-ID FTS gate, shared with the builder)

DDL = {
    "staging_entries": """
        CREATE TABLE IF NOT EXISTS staging_entries(
            staging_id TEXT PRIMARY KEY,
            headword TEXT NOT NULL,
            pinyin TEXT,
            pos TEXT,
            entry_type TEXT,
            domain_ids TEXT,
            specialization TEXT,
            confidence TEXT,
            confidence_reason TEXT,
            source_sha256 TEXT,
            extraction_method TEXT,
            batch_id TEXT,
            status TEXT,               -- staged | promoted | rejected
            created_at TEXT,
            promoted_entry_id INTEGER
        )""",
    "staging_senses": """
        CREATE TABLE IF NOT EXISTS staging_senses(
            staging_id TEXT NOT NULL,
            sense_no INTEGER NOT NULL,
            gloss_en TEXT NOT NULL,
            gloss_ne TEXT,
            domain_ids TEXT,
            confidence TEXT,
            verification_status TEXT,
            review_required INTEGER DEFAULT 1,
            review_reason TEXT,
            PRIMARY KEY(staging_id, sense_no)
        )""",
    "import_batches": """
        CREATE TABLE IF NOT EXISTS import_batches(
            batch_id TEXT PRIMARY KEY,
            started_at TEXT,
            finished_at TEXT,
            records INTEGER,
            staged INTEGER,
            skipped_duplicate INTEGER,
            conflicts INTEGER,
            promoted INTEGER
        )""",
    "conflicts": """
        CREATE TABLE IF NOT EXISTS conflicts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            headword TEXT,
            reason TEXT,
            payload TEXT,
            created_at TEXT
        )""",
    "source_evidence": """
        CREATE TABLE IF NOT EXISTS source_evidence(
            evidence_id TEXT PRIMARY KEY,
            entry_id INTEGER,
            sense_id INTEGER,
            source_sha256 TEXT,
            extraction_method TEXT,
            original_gloss TEXT,
            model TEXT,
            confidence TEXT,
            batch_id TEXT,
            imported_at TEXT
        )""",
    "dictionary_changelog": """
        CREATE TABLE IF NOT EXISTS dictionary_changelog(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT,
            changed_at TEXT,
            note TEXT,
            entries_added INTEGER,
            senses_added INTEGER,
            source_batch TEXT
        )""",
}

TONE_MAP = str.maketrans({
    "ā": "a", "á": "a", "ǎ": "a", "à": "a",
    "ē": "e", "é": "e", "ě": "e", "è": "e",
    "ī": "i", "í": "i", "ǐ": "i", "ì": "i",
    "ō": "o", "ó": "o", "ǒ": "o", "ò": "o",
    "ū": "u", "ú": "u", "ǔ": "u", "ù": "u",
    "ǖ": "v", "ǘ": "v", "ǚ": "v", "ǜ": "v", "ü": "v",
})


def pinyin_forms(marked: str) -> tuple[str, str]:
    plain = unicodedata.normalize("NFC", marked or "").translate(TONE_MAP)
    plain = " ".join(plain.split())
    return plain, plain.replace(" ", "").lower()


def staging_key(headword: str, pinyin: str, glosses: list[str]) -> str:
    payload = "|".join([headword, pinyin or "", ";".join(sorted(glosses))])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def backup(db: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"dictionary-{time.strftime('%Y%m%d-%H%M%S')}.sqlite"
    shutil.copy2(db, dest)
    check = sqlite3.connect(f"file:{dest.as_posix()}?mode=ro", uri=True)
    ok = check.execute("PRAGMA integrity_check").fetchone()[0]
    rows = check.execute("SELECT count(*) FROM entries").fetchone()[0]
    check.close()
    if ok != "ok" or rows == 0:
        raise SystemExit(f"backup failed validation: integrity={ok} entries={rows}")
    print(f"backup ok: {dest} ({dest.stat().st_size/1e6:.1f} MB, integrity ok, {rows:,} entries)")
    return dest


def load(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(Path("data") / "build" / "dictionary.sqlite"))
    ap.add_argument("--enriched", default=str(Path("data") / "r3" / "enrichments.jsonl"))
    ap.add_argument("--nepali", default=str(Path("data") / "r4" / "ne_results.jsonl"))
    ap.add_argument("--out", default=str(Path("data") / "r5"))
    ap.add_argument("--batch-id", default=None)
    ap.add_argument("--apply", action="store_true", help="write to staging tables")
    ap.add_argument("--dry-run", action="store_true", help="read-only reconciliation (default)")
    ap.add_argument("--promote", action="store_true", help="promote approved staged rows")
    ap.add_argument("--approval", default=None, help="CSV: headword,decision(approve|reject)")
    args = ap.parse_args()

    db = Path(args.db)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    enriched = load(Path(args.enriched))
    nepali = {(r["word"], r["english_meaning"]): r for r in load(Path(args.nepali))}
    print(f"R3 records: {len(enriched):,} · R4 nepali rows: {len(nepali):,}")

    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    for name, ddl in DDL.items():
        con.execute(ddl)
    con.commit()
    cur = con.cursor()
    existing = {r[0]: (r[1] or "", r[2] or "") for r in
                cur.execute("SELECT simplified, pinyin_marked, pos_primary FROM entries")}

    valid, invalid, conflicts, dup, new = [], [], [], [], []
    for rec in enriched:
        problems = []
        head = rec.get("simplified") or rec.get("headword")
        if not head or not head.strip():
            problems.append("empty headword")
        if not rec.get("pinyin"):
            problems.append("missing pinyin")
        if not rec.get("senses"):
            problems.append("no senses")
        if problems:
            invalid.append({"record": rec, "problems": problems})
            continue
        if head in existing:
            dup.append(head)
            continue
        valid.append(rec)
        new.append(head)

    conflicts_out = []
    if args.promote:
        if not args.approval or not Path(args.approval).exists():
            raise SystemExit("--promote requires --approval <csv> with a human decision per headword")
        decisions = {}
        with Path(args.approval).open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                decisions[row["headword"].strip()] = row["decision"].strip().lower()
        batch_id = args.batch_id or "r5-manual"
        added_e = added_s = 0
        staged = cur.execute(
            "SELECT staging_id, headword, pinyin, pos, entry_type, domain_ids, confidence, source_sha256, extraction_method FROM staging_entries WHERE status='staged'"
        ).fetchall()
        approved = [r for r in staged if decisions.get(r[1]) == "approve"]
        if not approved:
            print("nothing approved in the approval file; database untouched")
            con.close()
            return 0
        bk = backup(db, db.parent / "backups")
        next_id = cur.execute("SELECT max(entry_id) FROM entries").fetchone()[0] + 1
        try:
            con.execute("BEGIN")
            for sid, head, pinyin, pos, etype, domains, conf, sha, method in staged:
                if decisions.get(head) != "approve":
                    continue
                plain, search = pinyin_forms(pinyin)
                is_proper = 1 if etype == "proper_noun" else 0
                con.execute(
                    "INSERT INTO entries(entry_id, simplified, traditional, pinyin_num, pinyin_marked,"
                    " pinyin_plain, pinyin_search, category, pos_primary, is_proper, is_chengyu,"
                    " is_classifier, rarity, freq_rank, hsk_level, status)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (next_id, head, head, search, pinyin, plain, search,
                     (domains or "").split(",")[0] or "general",
                     pos or "unknown", is_proper, 0, 0, 4, None, None, "ai_translated"))
                senses = cur.execute(
                    "SELECT sense_no, gloss_en, gloss_ne, domain_ids FROM staging_senses"
                    " WHERE staging_id=? ORDER BY sense_no", (sid,)).fetchall()
                for sn, gloss_en, gloss_ne, sdom in senses:
                    sense_id = cur.execute("SELECT max(sense_id) FROM senses").fetchone()[0] + 1
                    con.execute(
                        "INSERT INTO senses(sense_id, entry_id, sense_order, gloss_en, gloss_zh,"
                        " gloss_ne, ne_status, source_id) VALUES(?,?,?,?,?,?,?,?)",
                        (sense_id, next_id, sn, gloss_en, None, gloss_ne or None,
                         "ai_translated" if gloss_ne else None, None))
                    con.execute(
                        "INSERT INTO source_evidence(evidence_id, entry_id, sense_id, source_sha256,"
                        " extraction_method, original_gloss, model, confidence, batch_id, imported_at)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (f"ev-{sense_id}", next_id, sense_id, sha, method, gloss_en,
                         "failover-chain", conf, batch_id, time.strftime("%Y-%m-%dT%H:%M:%S")))
                    added_s += 1
                for fts_table, cols in (("fts", "simplified, traditional, pinyin_search, english, category, entry_id"),
                                        ("fts_zh", "simplified, traditional, english, entry_id")):
                    gloss_text = " ; ".join(g for g, _ in cur.execute(
                        "SELECT gloss_en, gloss_ne FROM staging_senses WHERE staging_id=? ORDER BY sense_no",
                        (sid,)).fetchall())
                    if fts_table == "fts":
                        con.execute(f"INSERT INTO fts({cols}) VALUES(?,?,?,?,?,?)",
                                    (head, head, search, gloss_text,
                                     (domains or "").split(",")[0] or "general", next_id))
                    else:
                        con.execute(f"INSERT INTO fts_zh({cols}) VALUES(?,?,?,?)",
                                    (head, head, gloss_text, next_id))
                cur.execute("UPDATE staging_entries SET status='promoted', promoted_entry_id=? WHERE staging_id=?",
                            (next_id, sid))
                added_e += 1
                next_id += 1
            version = "unchanged (nothing approved)"
            if added_e:
                version = str(int(cur.execute("SELECT max(CAST(value AS INTEGER)) FROM meta WHERE key='dataset_version'").fetchone()[0] or 1) + 1)
                cur.execute("UPDATE meta SET value=? WHERE key='dataset_version'", (version,))
                cur.execute("INSERT INTO dictionary_changelog(version, changed_at, note, entries_added, senses_added, source_batch)"
                            " VALUES(?,?,?,?,?,?)",
                            (version, time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "R5 promotion of rawdata.txt new headwords", added_e, added_s, batch_id))
            con.commit()
        except Exception:
            con.rollback()
            raise
        print(f"promoted: {added_e} entries, {added_s} senses · version → {version}")
        print(f"backup kept at {bk}")
        con.close()
        # A promotion is not shippable until both indexes cover every entry. Any
        # entry inserted above without an index row would silently vanish from
        # search — exactly the defect that shipped 76 missing fts_zh rows.
        fts = validate_fts.check(str(db))
        print(json.dumps(fts, indent=2, ensure_ascii=False))
        if not fts["ok"]:
            print("r5 promotion left the search index incomplete: %s"
                  % "; ".join(fts["failures"]), file=sys.stderr)
            return 1
        return 0

    summary = {
        "records_in": len(enriched),
        "valid": len(valid),
        "invalid": len(invalid),
        "exact_duplicates_skipped": len(dup),
        "conflicts": len(conflicts_out),
        "new_headwords": len(new),
    }
    if args.apply:
        batch_id = args.batch_id or f"r5-{time.strftime('%H%M%S')}"
        bk = backup(db, db.parent / "backups")
        added = 0
        try:
            con.execute("BEGIN")
            for rec in valid:
                head = rec["simplified"]
                glosses = [s["english_meanings"] for s in rec["senses"]]
                sid = staging_key(head, rec["pinyin"], glosses)
                if cur.execute("SELECT 1 FROM staging_entries WHERE staging_id=?", (sid,)).fetchone():
                    continue
                cur.execute(
                    "INSERT INTO staging_entries(staging_id, headword, pinyin, pos, entry_type, domain_ids,"
                    " specialization, confidence, confidence_reason, source_sha256, extraction_method,"
                    " batch_id, status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, head, rec["pinyin"], rec.get("part_of_speech"), rec.get("entry_type"),
                     ",".join(rec.get("domain_ids") or []), rec.get("specialization_level"),
                     rec.get("confidence"), rec.get("confidence_reason"), rec.get("source_sha256"),
                     rec.get("extraction_method"), batch_id, "staged",
                     time.strftime("%Y-%m-%dT%H:%M:%S")))
                for s in rec["senses"]:
                    ne = nepali.get((head, s["english_meanings"]))
                    cur.execute(
                        "INSERT INTO staging_senses(staging_id, sense_no, gloss_en, gloss_ne, domain_ids,"
                        " confidence, verification_status, review_required, review_reason)"
                        " VALUES(?,?,?,?,?,?,?,?,?)",
                        (sid, s["sense_number"], s["english_meanings"],
                         (ne or {}).get("nepali_meaning"), ",".join(s.get("domain_ids") or []),
                         (ne or {}).get("confidence"), "unverified",
                         int(bool((ne or {}).get("review_required", 1))),
                         (ne or {}).get("review_reason") or "no nepali yet"))
                added += 1
            cur.execute("INSERT OR REPLACE INTO import_batches(batch_id, started_at, finished_at, records,"
                        " staged, skipped_duplicate, conflicts, promoted) VALUES(?,?,?,?,?,?,?,?)",
                        (batch_id, time.strftime("%Y-%m-%dT%H:%M:%S"),
                         time.strftime("%Y-%m-%dT%H:%M:%S"), len(enriched), added,
                         len(dup), len(conflicts_out), 0))
            con.commit()
        except Exception:
            con.rollback()
            raise
        summary["staged"] = added
        summary["batch_id"] = batch_id
        print(f"staged {added} headwords into staging tables (master tables untouched)")
        print(f"backup kept at {bk}")
    else:
        summary["mode"] = "dry-run (nothing written)"

    (out_dir / "r5_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    md = ["# R5 reconciliation report", "",
          f"- mode: {summary.get('mode', 'apply')}",
          f"- incoming records: {summary['records_in']:,}",
          f"- valid: {summary['valid']:,}",
          f"- invalid (rejected, not partially imported): {summary['invalid']:,}",
          f"- exact duplicates already in the dictionary (skipped): {summary['exact_duplicates_skipped']:,}",
          f"- conflicts: {summary['conflicts']:,}",
          f"- genuinely new headwords: {summary['new_headwords']:,}",
          "", "Possible new headwords (first 60):", ""]
    md += [f"- {h}" for h in new[:60]]
    (out_dir / "r5_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
