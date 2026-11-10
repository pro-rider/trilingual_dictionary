"""Apply the reviewed Nepali gloss corrections to a database, or dry-run them.

The corrections live in ``docs/NE-CORRECTIONS.json`` and were generated *from*
the database, so every ``old`` value is byte-exact. That turns a blind overwrite
into a drift check: if the database no longer holds the recorded value, this
refuses to write anything and says which sense drifted.

What it guarantees, in order:

1. every ``old`` matches the stored value (else exit 1, nothing written);
2. the backup, when one is passed, is byte-identical to the target before the
   first write (a wrong baseline is not a backup);
3. the update runs inside one transaction and touches exactly the recorded
   ``sense_id`` rows — the affected-row count must equal the correction count;
4. after the update, every other ``(sense_id, gloss_ne)`` pair is unchanged,
   proven by a digest comparison, not by trust;
5. ``PRAGMA integrity_check`` / ``foreign_key_check`` pass, per-table row counts
   are unchanged, and the encoding gate reports no replacement characters.

Usage:
    python tools/apply_ne_corrections.py                 # dry run, report only
    python tools/apply_ne_corrections.py --apply --backup %TEMP%\before.sqlite
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
DEFAULT_DB = BACKEND / "data" / "build" / "dictionary.sqlite"
DEFAULT_CORRECTIONS = REPO / "docs" / "NE-CORRECTIONS.json"

sys.path.insert(0, str(BACKEND))
from tools.check_encoding import check_database  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_corrections(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    records = doc.get("corrections") or []
    if not records:
        raise SystemExit("no corrections in %s" % path)
    seen = set()
    for rec in records:
        for key in ("sense_id", "old", "new"):
            if key not in rec:
                raise SystemExit("correction missing %r: %r" % (key, rec))
        if rec["sense_id"] in seen:
            raise SystemExit("duplicate sense_id %s" % rec["sense_id"])
        seen.add(rec["sense_id"])
        if rec["old"] == rec["new"]:
            raise SystemExit("sense %s: old equals new" % rec["sense_id"])
        if "\ufffd" in rec["new"]:
            raise SystemExit("sense %s: replacement character in new value" % rec["sense_id"])
    return records


def pair_digest(conn: sqlite3.Connection, exclude: set[int]) -> str:
    """Digest of every (sense_id, gloss_ne) pair, minus the corrected senses."""
    h = hashlib.sha256()
    rows = conn.execute("SELECT sense_id, gloss_ne FROM senses ORDER BY sense_id").fetchall()
    for sense_id, gloss in rows:
        if sense_id in exclude:
            continue
        h.update(("%d\x1f%s\x1e" % (sense_id, "" if gloss is None else gloss)).encode("utf-8"))
    total = sum(1 for sense_id, _ in rows if sense_id not in exclude)
    return "%s:%d" % (h.hexdigest(), total)


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE '%_fts%' AND name NOT LIKE 'sqlite_%'")]
    counts = {}
    for name in names:
        counts[name] = conn.execute('SELECT count(*) FROM "%s"' % name).fetchone()[0]
    return counts


def run(db: Path, corrections_path: Path, apply: bool, backup: Path | None) -> dict:
    records = load_corrections(corrections_path)
    report: dict = {
        "run_id": "%s-apply-ne-corrections" % (Path(db).name),
        "database": str(db),
        "corrections_file": str(corrections_path),
        "mode": "apply" if apply else "dry-run",
        "corrections": len(records),
        "checks": [],
        "drift": [],
    }

    def check(name: str, ok: bool, detail: str) -> bool:
        report["checks"].append({"name": name, "ok": ok, "detail": detail})
        return ok

    if not db.exists():
        check("database_exists", False, "missing: %s" % db)
        report["ok"] = False
        report["verdict"] = "STOP"
        return report

    before_hash = sha256(db)
    report["before_sha256"] = before_hash
    if backup is not None:
        if not backup.exists():
            check("backup_exists", False, "missing: %s" % backup)
            report["ok"] = False
            report["verdict"] = "STOP"
            return report
        backup_hash = sha256(backup)
        report["backup_sha256"] = backup_hash
        if not check("backup_matches_target", backup_hash == before_hash,
                     "backup %s vs target %s" % (backup_hash[:12], before_hash[:12])):
            report["ok"] = False
            report["verdict"] = "STOP"
            return report
    elif apply:
        check("backup_present", False, "refusing to write without --backup")
        report["ok"] = False
        report["verdict"] = "STOP"
        return report

    conn = sqlite3.connect(str(db), timeout=30)
    try:
        # 1. drift check — no writes if any recorded value moved.
        drift = []
        for rec in records:
            row = conn.execute("SELECT gloss_ne FROM senses WHERE sense_id = ?",
                               (rec["sense_id"],)).fetchone()
            if row is None:
                drift.append({"sense_id": rec["sense_id"], "problem": "sense missing"})
            elif row[0] != rec["old"]:
                drift.append({"sense_id": rec["sense_id"], "problem": "value drifted",
                              "expected": rec["old"], "found": row[0]})
        report["drift"] = drift
        if not check("no_drift", not drift, "%d drifted of %d" % (len(drift), len(records))):
            report["ok"] = False
            report["verdict"] = "STOP"
            return report

        ids = {r["sense_id"] for r in records}
        counts_before = table_counts(conn)
        digest_before = pair_digest(conn, ids)
        integrity_before = conn.execute("PRAGMA integrity_check").fetchone()[0]

        if not apply:
            report["ok"] = True
            report["verdict"] = "DRY-RUN-OK"
            report["after_sha256"] = before_hash
            return report

        # 2. one transaction, exact-row-count assertion.
        try:
            conn.execute("BEGIN IMMEDIATE")
            changed = 0
            for rec in records:
                cur = conn.execute(
                    "UPDATE senses SET gloss_ne = ? WHERE sense_id = ? AND gloss_ne = ?",
                    (rec["new"], rec["sense_id"], rec["old"]))
                changed += cur.rowcount
            if changed != len(records):
                raise RuntimeError("updated %d rows, expected %d" % (changed, len(records)))
            for rec in records:
                got = conn.execute("SELECT gloss_ne FROM senses WHERE sense_id = ?",
                                   (rec["sense_id"],)).fetchone()[0]
                if got != rec["new"]:
                    raise RuntimeError("sense %s not updated" % rec["sense_id"])

            counts_after = table_counts(conn)
            digest_after = pair_digest(conn, ids)
            integrity_after = conn.execute("PRAGMA integrity_check").fetchone()[0]
            fk_after = conn.execute("PRAGMA foreign_key_check").fetchall()

            problems = []
            if counts_after != counts_before:
                problems.append("row counts changed: %r" % {
                    k: (counts_before.get(k), counts_after.get(k))
                    for k in set(counts_before) | set(counts_after)
                    if counts_before.get(k) != counts_after.get(k)})
            if digest_after != digest_before:
                problems.append("unrelated sense rows changed: %s vs %s"
                                % (digest_before[:20], digest_after[:20]))
            if integrity_after != "ok":
                problems.append("integrity_check: %s" % integrity_after)
            if fk_after:
                problems.append("foreign_key_check: %d violations" % len(fk_after))
            if problems:
                raise RuntimeError("; ".join(problems))
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - any failure must roll back
            conn.rollback()
            check("transaction", False, "%s (rolled back)" % exc)
            report["ok"] = False
            report["verdict"] = "STOP"
            return report

        check("transaction", True, "%d rows updated, others unchanged (%s:%s)"
              % (changed, digest_after.split(":")[0][:12], digest_after.split(":")[1]))
        report["changed_rows"] = changed
    finally:
        conn.close()

    # 3. independent re-open: hash, integrity, encoding.
    after_hash = sha256(db)
    report["after_sha256"] = after_hash
    check("database_changed_at_least_once", after_hash != before_hash, "hash moved")
    enc = check_database(db, strict=False)
    report["encoding"] = {"ok": enc["ok"], "errors": len(enc["errors"]),
                          "warnings": len(enc["warnings"])}
    check("no_replacement_characters",
          not any("U+FFFD" in e["reason"] for e in enc["errors"]),
          "encoding errors: %s" % [e["reason"] for e in enc["errors"]][:3])

    report["ok"] = all(c["ok"] for c in report["checks"])
    report["verdict"] = "APPLIED" if report["ok"] else "STOP"
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--corrections", type=Path, default=DEFAULT_CORRECTIONS)
    ap.add_argument("--apply", action="store_true", help="write; without it this is a dry run")
    ap.add_argument("--backup", type=Path, help="byte-identical copy of --db, required with --apply")
    ap.add_argument("--json", type=Path, help="write the run-log here")
    args = ap.parse_args(argv)

    report = run(args.db, args.corrections, args.apply, args.backup)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    print("NE CORRECTIONS: %s" % report["verdict"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
