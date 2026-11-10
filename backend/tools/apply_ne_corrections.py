"""Apply the reviewed text corrections to a database, or dry-run them.

The corrections live in ``docs/NE-CORRECTIONS.json`` and were generated *from*
the database, so every ``old`` value is byte-exact. That turns a blind overwrite
into a drift check: if a row no longer holds the recorded value *and* does not
already hold the corrected value, this refuses to write anything and says which
row drifted.

Each record names its own table, key column, text column and key value, so the
same tool covers ``senses.gloss_ne`` and ``examples.ne`` without growing a
special case per table.

What it guarantees, in order:

1. every record is either pending (value == old) or already applied (== new);
   anything else is drift and stops the run with nothing written;
2. a backup, when passed, is byte-identical to the target before the first write;
3. the update runs inside one transaction, per table, and the affected-row count
   must equal the number of pending records;
4. after the update every other (key, value) pair is unchanged, proven by a
   digest comparison, and per-table row counts are unchanged;
5. ``PRAGMA integrity_check`` / ``foreign_key_check`` pass, no replacement
   character survives, and re-running the same file changes nothing.

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

REQUIRED = ("table", "key_column", "key_value", "column", "old", "new")


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
        for key in REQUIRED:
            if key not in rec:
                raise SystemExit("correction missing %r: %r" % (key, rec))
        identity = (rec["table"], rec["key_column"], rec["key_value"], rec["column"])
        if identity in seen:
            raise SystemExit("duplicate correction target %r" % (identity,))
        seen.add(identity)
        if rec["old"] == rec["new"]:
            raise SystemExit("%r: old equals new" % (identity,))
        if "\ufffd" in rec["new"]:
            raise SystemExit("%r: replacement character in new value" % (identity,))
    return records


def _groups(records: list[dict]) -> dict[tuple[str, str], set]:
    """(table, column) -> set of key values covered by the corrections."""
    groups: dict[tuple[str, str], set] = {}
    for rec in records:
        groups.setdefault((rec["table"], rec["column"]), set()).add(rec["key_value"])
    return groups


def column_digest(conn: sqlite3.Connection, table: str, column: str,
                  key_column: str, exclude: set) -> str:
    """Digest of every (key, value) pair in one column, minus the corrected keys."""
    h = hashlib.sha256()
    rows = conn.execute('SELECT "%s", "%s" FROM "%s" ORDER BY "%s"'
                        % (key_column, column, table, key_column)).fetchall()
    counted = 0
    for key, value in rows:
        if key in exclude:
            continue
        counted += 1
        h.update(("%s\x1f%s\x1e" % (key, "" if value is None else value)).encode("utf-8"))
    return "%s:%d" % (h.hexdigest(), counted)


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE '%_fts%' AND name NOT LIKE 'sqlite_%'")]
    return {name: conn.execute('SELECT count(*) FROM "%s"' % name).fetchone()[0]
            for name in names}


def run(db: Path, corrections_path: Path, apply: bool, backup: Path | None) -> dict:
    records = load_corrections(corrections_path)
    report: dict = {
        "run_id": "%s-apply-ne-corrections" % Path(db).name,
        "database": str(db),
        "corrections_file": str(corrections_path),
        "mode": "apply" if apply else "dry-run",
        "corrections": len(records),
        "checks": [],
        "pending": [],
        "already_applied": [],
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
        for rec in records:
            row = conn.execute('SELECT "%s" FROM "%s" WHERE "%s" = ?'
                               % (rec["column"], rec["table"], rec["key_column"]),
                               (rec["key_value"],)).fetchone()
            if row is None:
                report["drift"].append({"target": rec["key_value"], "table": rec["table"],
                                        "problem": "row missing"})
            elif row[0] == rec["new"]:
                report["already_applied"].append(rec["key_value"])
            elif row[0] == rec["old"]:
                report["pending"].append(rec["key_value"])
            else:
                report["drift"].append({"target": rec["key_value"], "table": rec["table"],
                                        "problem": "value drifted", "expected": rec["old"],
                                        "found": row[0]})
        if not check("no_drift", not report["drift"],
                     "%d drifted, %d pending, %d already applied of %d"
                     % (len(report["drift"]), len(report["pending"]),
                        len(report["already_applied"]), len(records))):
            report["ok"] = False
            report["verdict"] = "STOP"
            return report

        groups = _groups(records)
        digests_before = {k: column_digest(conn, k[0], k[1],
                                          next(r["key_column"] for r in records
                                               if r["table"] == k[0] and r["column"] == k[1]),
                                          v) for k, v in groups.items()}
        counts_before = table_counts(conn)

        if not apply:
            report["ok"] = True
            report["verdict"] = "DRY-RUN-OK"
            report["after_sha256"] = before_hash
            return report

        pending = [r for r in records if r["key_value"] in report["pending"]]
        if not pending:
            check("nothing_to_do", True, "all corrections already applied")
            report["changed_rows"] = 0
        else:
            try:
                conn.execute("BEGIN IMMEDIATE")
                changed = 0
                for rec in pending:
                    cur = conn.execute(
                        'UPDATE "%s" SET "%s" = ? WHERE "%s" = ? AND "%s" = ?'
                        % (rec["table"], rec["column"], rec["key_column"], rec["column"]),
                        (rec["new"], rec["key_value"], rec["old"]))
                    changed += cur.rowcount
                if changed != len(pending):
                    raise RuntimeError("updated %d rows, expected %d" % (changed, len(pending)))
                for rec in pending:
                    got = conn.execute('SELECT "%s" FROM "%s" WHERE "%s" = ?'
                                       % (rec["column"], rec["table"], rec["key_column"]),
                                       (rec["key_value"],)).fetchone()[0]
                    if got != rec["new"]:
                        raise RuntimeError("%s %s not updated" % (rec["table"], rec["key_value"]))

                digests_after = {k: column_digest(conn, k[0], k[1],
                                                 next(r["key_column"] for r in records
                                                      if r["table"] == k[0] and r["column"] == k[1]),
                                                 v) for k, v in groups.items()}
                counts_after = table_counts(conn)
                integrity_after = conn.execute("PRAGMA integrity_check").fetchone()[0]
                fk_after = conn.execute("PRAGMA foreign_key_check").fetchall()

                problems = []
                if counts_after != counts_before:
                    problems.append("row counts changed: %r" % sorted(
                        (k, counts_before.get(k), counts_after.get(k))
                        for k in set(counts_before) | set(counts_after)
                        if counts_before.get(k) != counts_after.get(k)))
                for key, digest in digests_before.items():
                    if digests_after[key] != digest:
                        problems.append("unrelated rows changed in %s.%s: %s vs %s"
                                        % (key[0], key[1], digest[:20],
                                           digests_after[key][:20]))
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

            check("transaction", True, "%d rows updated, other rows unchanged" % changed)
            report["changed_rows"] = changed
    finally:
        conn.close()

    after_hash = sha256(db)
    report["after_sha256"] = after_hash
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
