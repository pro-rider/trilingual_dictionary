"""Propagate the reviewed dictionary corrections into the governance store.

`dictionary.sqlite` is the authoritative original for legacy Nepali text
(`docs/PHASE2.1-CORRECTIONS.md` §3), and `translations.db` keeps an import copy of
it. Editing one without the other creates two truths, and
`tests/test_resolution.py::test_real_data_one_nepali_line_per_sense` fails on
exactly that divergence. This tool performs the second half of the same edit.

It changes only ``translations.text`` for the corrected senses, keeps the row
identity and every governance column untouched, and proves:

1. each store row now holds the recorded ``old`` value (or already ``new``);
2. the backup is byte-identical to the target before the first write;
3. the affected-row count equals the pending count;
4. every other (translation_id, text) pair is unchanged, by digest;
5. row counts and ``PRAGMA integrity_check`` are unchanged after the write.

Usage:
    python tools/sync_legacy_translation_text.py                  # dry run
    python tools/sync_legacy_translation_text.py --apply --backup <path-to-copy>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_STORE = BACKEND / "data" / "build" / "translations.db"
DEFAULT_CORRECTIONS = BACKEND.parent / "docs" / "NE-CORRECTIONS.json"
ORIGIN = "dictionary.sqlite:senses.ne"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sense_records(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return [r for r in doc.get("corrections", []) if r["table"] == "senses"]


def _digest(conn: sqlite3.Connection, exclude: set) -> str:
    h = hashlib.sha256()
    counted = 0
    for translation_id, text in conn.execute(
            "SELECT translation_id, text FROM translations ORDER BY translation_id"):
        if translation_id in exclude:
            continue
        counted += 1
        h.update(("%s\x1f%s\x1e" % (translation_id, "" if text is None else text)).encode("utf-8"))
    return "%s:%d" % (h.hexdigest(), counted)


def run(store: Path, corrections_path: Path, apply: bool, backup: Path | None) -> dict:
    records = _sense_records(corrections_path)
    report: dict = {
        "run_id": "sync-legacy-translation-text",
        "store": str(store),
        "corrections_file": str(corrections_path),
        "mode": "apply" if apply else "dry-run",
        "corrections": len(records),
        "checks": [],
        "pending": [],
        "already_applied": [],
        "drift": [],
        "missing": [],
    }

    def check(name: str, ok: bool, detail: str) -> bool:
        report["checks"].append({"name": name, "ok": ok, "detail": detail})
        return ok

    if not store.exists():
        check("store_exists", False, "missing: %s" % store)
        report.update(ok=False, verdict="STOP")
        return report

    before_hash = sha256(store)
    report["before_sha256"] = before_hash
    if backup is not None:
        if not backup.exists():
            check("backup_exists", False, "missing: %s" % backup)
            report.update(ok=False, verdict="STOP")
            return report
        backup_hash = sha256(backup)
        report["backup_sha256"] = backup_hash
        if not check("backup_matches_target", backup_hash == before_hash,
                     "backup %s vs target %s" % (backup_hash[:12], before_hash[:12])):
            report.update(ok=False, verdict="STOP")
            return report
    elif apply:
        check("backup_present", False, "refusing to write without --backup")
        report.update(ok=False, verdict="STOP")
        return report

    conn = sqlite3.connect(str(store), timeout=30)
    try:
        targets: dict[int, str] = {}
        for rec in records:
            rows = conn.execute(
                "SELECT translation_id, text FROM translations "
                "WHERE origin_source = ? AND origin_record_id = ?",
                (ORIGIN, str(rec["key_value"]))).fetchall()
            if not rows:
                report["missing"].append(rec["key_value"])
                continue
            if len(rows) > 1:
                report["drift"].append({"sense_id": rec["key_value"],
                                        "problem": "multiple store rows: %d" % len(rows)})
                continue
            translation_id, text = rows[0]
            targets[translation_id] = rec["key_value"]
            if text == rec["new"]:
                report["already_applied"].append(rec["key_value"])
            elif text == rec["old"]:
                report["pending"].append(rec["key_value"])
            else:
                report["drift"].append({"sense_id": rec["key_value"], "problem": "value drifted",
                                        "expected": rec["old"], "found": text})

        if not check("all_targets_resolved", not report["missing"] and not report["drift"],
                     "%d pending, %d already applied, %d missing, %d drifted"
                     % (len(report["pending"]), len(report["already_applied"]),
                        len(report["missing"]), len(report["drift"]))):
            report.update(ok=False, verdict="STOP")
            return report

        exclude = set(targets)
        digest_before = _digest(conn, exclude)
        count_before = conn.execute("SELECT count(*) FROM translations").fetchone()[0]

        if not apply:
            report.update(ok=True, verdict="DRY-RUN-OK", after_sha256=before_hash)
            return report

        pending = [r for r in records if r["key_value"] in report["pending"]]
        if not pending:
            check("nothing_to_do", True, "store already matches the corrections")
            report["changed_rows"] = 0
        else:
            try:
                conn.execute("BEGIN IMMEDIATE")
                changed = 0
                for rec in pending:
                    cur = conn.execute(
                        "UPDATE translations SET text = ? "
                        "WHERE origin_source = ? AND origin_record_id = ? AND text = ?",
                        (rec["new"], ORIGIN, str(rec["key_value"]), rec["old"]))
                    changed += cur.rowcount
                if changed != len(pending):
                    raise RuntimeError("updated %d rows, expected %d" % (changed, len(pending)))
                digest_after = _digest(conn, exclude)
                count_after = conn.execute("SELECT count(*) FROM translations").fetchone()[0]
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                problems = []
                if digest_after != digest_before:
                    problems.append("unrelated store rows changed: %s vs %s"
                                    % (digest_before[:20], digest_after[:20]))
                if count_after != count_before:
                    problems.append("row count changed: %d -> %d" % (count_before, count_after))
                if integrity != "ok":
                    problems.append("integrity_check: %s" % integrity)
                if problems:
                    raise RuntimeError("; ".join(problems))
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                check("transaction", False, "%s (rolled back)" % exc)
                report.update(ok=False, verdict="STOP")
                return report
            check("transaction", True, "%d store rows updated, others unchanged" % changed)
            report["changed_rows"] = changed
    finally:
        conn.close()

    report["after_sha256"] = sha256(store)
    report["ok"] = all(c["ok"] for c in report["checks"])
    report["verdict"] = "APPLIED" if report["ok"] else "STOP"
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--corrections", type=Path, default=DEFAULT_CORRECTIONS)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    report = run(args.store, args.corrections, args.apply, args.backup)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    print("STORE SYNC: %s" % report["verdict"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
