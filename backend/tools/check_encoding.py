"""UTF-8 / Devanagari integrity gate.

Why this exists: `r1_clean.py` rejects U+FFFD in *input documents*, and
`classify_script_mix.py` looks at Latin/Cyrillic mixing, but nothing checked the
*shipped* dictionary text before a bulk write touched it. A mojibake row written
once is cheap to detect here and expensive to find after it reaches the UI.

Read-only. Never writes to the database it inspects. Exits non-zero when a
problem is found, so it can be used as a gate (`PROTOCOL.md` rule 9), and its
`--selftest` proves the detector actually bites instead of passing vacuously.

Usage:
    python tools/check_encoding.py --db data/build/dictionary.sqlite
    python tools/check_encoding.py --db data/build/dictionary.sqlite --strict
    python tools/check_encoding.py --file docs/AGENT-NEPALI.md
    python tools/check_encoding.py --selftest
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import unicodedata
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_DB = BACKEND / "data" / "build" / "dictionary.sqlite"

# Columns whose contract is Devanagari-only (docs/AGENT-NEPALI.md §Verifier).
DEVANAGARI_COLUMNS = {"gloss_ne", "value_ne", "ne"}

# Sequences that survive a double-decode of UTF-8 as Latin-1/CP1252. These do not
# contain U+FFFD at all, which is exactly why a replacement-character scan alone
# misses them.
MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "à¤", "à¥", "à¦", "ï¿½")

# Devanagari block U+0900..U+097F.
DEVA_START, DEVA_END = 0x0900, 0x097F


def _is_devanagari(ch: str) -> bool:
    return DEVA_START <= ord(ch) <= DEVA_END


def inspect_text(value: str, *, column: str = "") -> list[tuple[str, str]]:
    """Return (severity, reason) pairs for one text cell. Pure, so it is testable."""
    found: list[tuple[str, str]] = []

    if "\ufffd" in value:
        found.append(("error", "U+FFFD replacement character"))
    if "\x00" in value:
        found.append(("error", "NUL byte inside text"))

    for ch in value:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            found.append(("error", "unpaired surrogate"))
            break
        if unicodedata.category(ch) in ("Cc", "Cs") and ch not in "\t\n\r":
            found.append(("error", "control character U+%04X" % code))
            break

    for marker in MOJIBAKE_MARKERS:
        if marker in value:
            found.append(("error", "mojibake marker %r" % marker))
            break

    if column in DEVANAGARI_COLUMNS and value.strip():
        if any(ch.isascii() and ch.isalpha() for ch in value):
            found.append(("warn", "Latin letters in a Devanagari-only column"))
        if not any(_is_devanagari(ch) for ch in value):
            found.append(("warn", "no Devanagari codepoint in a Nepali column"))

    return found


def _text_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
    return [r[1] for r in rows if (r[2] or "").upper().startswith("TEXT")]


def _load_allowlist(path: Path | None) -> list[dict]:
    """Suppressions for warnings that are correct by design, never for errors."""
    if path is None or not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    entries = doc.get("entries") or []
    for entry in entries:
        for key in ("table", "column", "row", "value", "reason"):
            if key not in entry:
                raise SystemExit("allowlist entry missing %r: %r" % (key, entry))
    return entries


def check_database(path: Path, *, strict: bool = False,
                   allowlist: list[dict] | None = None) -> dict:
    """Scan every TEXT cell of every ordinary table. Returns a JSON-ready report."""
    errors: list[dict] = []
    warns: list[dict] = []
    allowed: list[dict] = []
    tables = 0
    cells = 0

    if not path.exists():
        return {"ok": False, "error": "database not found: %s" % path,
                "errors": [], "warnings": [], "allowed": [], "tables": 0, "cells": 0}

    conn = sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE '%_fts%' AND name NOT LIKE 'sqlite_%'").fetchall()]
        for table in names:
            cols = _text_columns(conn, table)
            if not cols:
                continue
            tables += 1
            # Row identity for the report: prefer an integer primary key.
            pk = None
            for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall():
                if r[5]:
                    pk = r[1]
                    break
            select = ", ".join('"%s"' % c for c in cols)
            ident = ',"%s" AS __rowid' % pk if pk else ", rowid AS __rowid"
            cursor = conn.execute('SELECT %s%s FROM "%s"' % (select, ident, table))
            for row in cursor:
                values = row[: len(cols)]
                rowid = row[-1]
                for column, value in zip(cols, values):
                    if not isinstance(value, str):
                        continue
                    cells += 1
                    for severity, reason in inspect_text(value, column=column):
                        record = {"table": table, "column": column, "row": rowid,
                                  "reason": reason, "sample": value[:60]}
                        if severity == "error":
                            errors.append(record)
                            continue
                        # A suppression must match value and location exactly, so a
                        # newly corrupted row cannot hide behind an old exception.
                        match = next((a for a in (allowlist or [])
                                      if a["table"] == table and a["column"] == column
                                      and a["row"] == rowid and a["value"] == value), None)
                        if match is not None:
                            record["reason"] = reason
                            record["allow_reason"] = match["reason"]
                            allowed.append(record)
                            continue
                        warns.append(record)
    finally:
        conn.close()

    ok = not errors and (not strict or not warns)
    return {"ok": ok, "database": str(path), "errors": errors,
            "warnings": warns, "allowed": allowed, "tables": tables, "cells": cells,
            "strict": strict}


def check_file(path: Path) -> dict:
    """Same detectors applied to a UTF-8 text file, byte-level strictness included."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
        decode = "ok"
    except UnicodeDecodeError as exc:
        return {"ok": False, "file": str(path), "decode": "error",
                "errors": [{"reason": "invalid UTF-8 at byte %d: %s"
                            % (exc.start, exc.reason)}]}
    found = [r for r in inspect_text(text) if r[0] == "error"]
    return {"ok": not found, "file": str(path), "decode": decode,
            "errors": [{"reason": reason} for _, reason in found]}


def selftest() -> dict:
    """Negative control: the detector must fire on known-bad text.

    A gate that cannot fail is a comment. This builds a throwaway database with
    one good row and four kinds of corruption, then requires each to be caught.
    """
    tmp = Path(tempfile.mkdtemp(prefix="encoding_selftest_"))
    db_path = tmp / "bad.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, gloss_ne TEXT, note TEXT)")
    rows = [
        (1, "किताब", "ok"),
        (2, "किताब\ufffd", "ok"),
        (3, "à¤•à¤¿à¤¤à¤¾à¤¬", "ok"),   # double-decoded, no U+FFFD anywhere
        (4, "book", "ok"),
        (5, "किताब", "bad\x00byte"),   # bound, never interpolated into SQL
    ]
    conn.executemany("INSERT INTO t (id, gloss_ne, note) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()

    report = check_database(db_path, strict=True)
    reasons = {e["reason"].split(" ")[0] for e in report["errors"]}
    expected = {"U+FFFD", "mojibake", "NUL"}
    caught_errors = expected.issubset(reasons)
    caught_warn = any("Latin letters" in w["reason"] or "no Devanagari" in w["reason"]
                      for w in report["warnings"])
    ok = caught_errors and caught_warn and report["ok"] is False
    return {"ok": ok, "caught_errors": caught_errors,
            "caught_devanagari_warning": caught_warn,
            "errors_found": len(report["errors"]),
            "warnings_found": len(report["warnings"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--db", type=Path, help="SQLite database to scan")
    group.add_argument("--file", type=Path, action="append",
                       help="UTF-8 text file to scan (repeatable)")
    group.add_argument("--selftest", action="store_true",
                       help="prove the detector catches known-bad input")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings (Latin in Nepali columns) as failures")
    parser.add_argument("--allowlist", type=Path,
                        default=BACKEND.parent / "docs" / "ENCODING-ALLOWLIST.json",
                        help="warnings that are correct by design (matched by row and value)")
    parser.add_argument("--no-allowlist", action="store_true",
                        help="ignore the allowlist file; every warning counts")
    parser.add_argument("--json", type=Path, help="also write the report here")
    args = parser.parse_args(argv)

    allow = [] if args.no_allowlist else _load_allowlist(args.allowlist)

    if args.selftest:
        report = selftest()
        ok = report["ok"]
    elif args.db:
        report = check_database(args.db, strict=args.strict, allowlist=allow)
        ok = report["ok"]
    else:
        report = {"ok": True, "files": []}
        for path in args.file:
            one = check_file(path)
            report["files"].append(one)
            ok = ok and one["ok"]
        ok = bool(report["ok"] and report["files"]) and all(f["ok"] for f in report["files"])

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    print(text)
    if not ok:
        # Non-zero exit, never a bare assert: `python -O` must not turn this off.
        print("ENCODING GATE: FAILED", file=sys.stderr)
        return 1
    print("ENCODING GATE: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
