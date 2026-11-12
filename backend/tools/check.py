"""`make check` — one command that runs everything a release must pass.

Steps, in order (fail fast, but report every step that ran):

1. backend unit tests (pytest)
2. search-ranking regression suite (part of pytest, called out separately so a
   ranking break is obvious in the summary)
3. licence audit of the release database (build_release_db.py:audit, on a temp
   copy so the working file is untouched)
4. database integrity + foreign keys + schema version
5. encoding gate (strict) if the tool is present
6. `flutter analyze` (client)
7. `flutter test` (client, may skip a DB-dependent group)

Run:  python tools/check.py            (from backend/)
      python tools/check.py --fast      (skip flutter)
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
PY = sys.executable
DB = BACKEND / "data" / "build" / "dictionary.sqlite"


def _flutter() -> str | None:
    """Locate the flutter launcher.

    subprocess on Windows does not resolve `.bat` through PATH the way a shell
    does, so the name alone raises WinError 2 even when flutter is installed.
    """
    import os
    import shutil

    explicit = os.environ.get("FLUTTER_BIN")
    if explicit and Path(explicit).exists():
        return explicit
    return shutil.which("flutter.bat") or shutil.which("flutter")


FLUTTER = _flutter()


def run(label: str, cmd: list[str], cwd: Path) -> bool:
    print(f"\n=== {label} ===")
    print(" ".join(cmd))
    proc = subprocess.run(cmd, cwd=cwd, text=True)
    ok = proc.returncode == 0
    print(f"--- {label}: {'PASS' if ok else 'FAIL'}")
    return ok


def licence_audit() -> bool:
    """Run the real audit against a copy, exactly as the release build would."""
    print("\n=== licence audit (release rules) ===")
    sys.path.insert(0, str(BACKEND))
    from tools import build_release_db as brel  # noqa: WPS433

    if not DB.exists():
        print("--- licence audit: SKIP (no working database)")
        return True
    tmp = Path(tempfile.mkdtemp()) / "audit.sqlite"
    shutil.copy2(DB, tmp)
    con = sqlite3.connect(tmp)
    dropped = brel.drop_forbidden(con)
    con.commit()
    problems = brel.audit(con)
    con.close()
    tmp.unlink(missing_ok=True)
    print(f"dropped candidate tables: {', '.join(dropped) or '(none)'}")
    for problem in problems:
        print("  problem:", problem)
    print(f"--- licence audit: {'PASS' if not problems else 'FAIL'}")
    return not problems


def db_integrity() -> bool:
    print("\n=== database integrity ===")
    if not DB.exists():
        print("--- integrity: SKIP (no working database)")
        return True
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    foreign = con.execute("PRAGMA foreign_key_check").fetchall()
    schema = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    con.close()
    print(f"integrity_check={integrity}  foreign_key_problems={len(foreign)}  "
          f"schema={schema[0] if schema else None}")
    ok = integrity == "ok" and not foreign and schema and schema[0] == "v005"
    print(f"--- integrity: {'PASS' if ok else 'FAIL'}")
    return bool(ok)


def encoding_gate() -> bool:
    print("\n=== encoding gate (strict) ===")
    tool = BACKEND / "tools" / "check_encoding.py"
    if not tool.exists():
        print("--- encoding gate: SKIP (tool not present)")
        return True
    return run("encoding gate (strict)",
               [PY, str(tool), "--db", str(DB), "--strict"], BACKEND)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="skip the Flutter steps")
    args = ap.parse_args(argv)

    results: list[tuple[str, bool]] = []
    results.append(("backend tests", run(
        "backend tests", [PY, "-m", "pytest", "-q"], BACKEND)))
    results.append(("ranking regression", run(
        "ranking regression",
        [PY, "-m", "pytest", "tests/test_search_ranking.py", "-q"], BACKEND)))
    results.append(("licence audit", licence_audit()))
    results.append(("db integrity", db_integrity()))
    results.append(("encoding gate", encoding_gate()))

    if not args.fast:
        if FLUTTER is None:
            print("\n=== flutter ===")
            print("flutter not found on PATH and FLUTTER_BIN is unset — "
                  "SKIPPED, so this run does not cover the client")
            results.append(("flutter analyze", False))
            results.append(("flutter test", False))
        else:
            results.append(("flutter analyze", run(
                "flutter analyze", [FLUTTER, "analyze", "--no-pub"], REPO)))
            results.append(("flutter test", run(
                "flutter test", [FLUTTER, "test", "--no-pub", "-r", "compact"], REPO)))

    print("\n================ SUMMARY ================")
    failed = 0
    for label, ok in results:
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
        failed += 0 if ok else 1
    print(f"{len(results) - failed}/{len(results)} steps passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
