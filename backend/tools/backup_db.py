"""Backup and restore the working database, and prove a restore works.

Two commands, both safe to run at any time:

    python tools/backup_db.py                 # timestamped copy + checksum file
    python tools/backup_db.py --list          # show the backups
    python tools/backup_db.py --verify <file> # restore-test a backup into a temp
                                              # copy and compare against it

`--verify` is the part that matters: a backup nobody ever restored is a guess.
It copies HEAD (or `integrity_check`-clean) and compares table counts and the
sha256 of every table's rows with the live file, so a truncated or half-written
copy is caught before it is needed.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKING_DB = REPO / "backend" / "data" / "build" / "dictionary.sqlite"
BACKUP_DIR = REPO / "backend" / "data" / "build" / "backups"

TABLES_FOR_DIGEST = ["entries", "senses", "examples", "images", "gloss_provenance",
                     "words3000_candidates", "gloss_zh_wikt_candidates",
                     "gloss_zh_candidates", "launch_set"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table_digest(path: Path) -> dict[str, tuple[int, str]]:
    """Rows plus a content hash per table, so counts alone cannot hide edits."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    out: dict[str, tuple[int, str]] = {}
    for table in TABLES_FOR_DIGEST:
        try:
            rows = con.execute(f"SELECT * FROM {table}").fetchall()
        except sqlite3.OperationalError:
            continue
        payload = repr(sorted(repr(r) for r in rows)).encode()
        out[table] = (len(rows), hashlib.sha256(payload).hexdigest())
    con.close()
    return out


def integrity_ok(path: Path) -> bool:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


def backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"dictionary.sqlite.bak-{stamp}"
    shutil.copy2(WORKING_DB, target)
    digest = sha256_file(target)
    target.with_suffix(target.suffix + ".sha256").write_text(
        f"{digest}  {target.name}\n", encoding="utf-8")
    print(f"backup   {target}  ({target.stat().st_size:,} bytes)")
    print(f"sha256   {digest}")
    if not integrity_ok(target):
        raise SystemExit("backup failed integrity_check — do not rely on it")
    print("integrity ok")
    return target


def verify(path: Path) -> bool:
    """Restore the backup into a temp file and compare it with the live DB."""
    tmp = BACKUP_DIR / "_restore_test.sqlite"
    shutil.copy2(path, tmp)
    ok = True
    if not integrity_ok(tmp):
        print("FAIL: restored copy fails integrity_check")
        ok = False
    live = table_digest(WORKING_DB)
    restored = table_digest(tmp)
    for table, (count, digest) in live.items():
        if table not in restored:
            print(f"FAIL: table {table} missing from the backup")
            ok = False
            continue
        if restored[table][0] != count:
            print(f"FAIL: {table} has {restored[table][0]} rows, live has {count}")
            ok = False
        elif restored[table][1] != digest:
            print(f"FAIL: {table} content differs (same row count)")
            ok = False
        else:
            print(f"ok: {table} {count} rows")
    tmp.unlink(missing_ok=True)
    print("RESTORE TEST PASSED" if ok else "RESTORE TEST FAILED")
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--verify", metavar="FILE")
    args = ap.parse_args(argv)

    if args.list:
        for path in sorted(BACKUP_DIR.glob("dictionary.sqlite.bak-*")):
            if path.suffix == ".sha256":
                continue
            print(f"{path.name}  {path.stat().st_size:,} bytes")
        return 0
    if args.verify:
        return 0 if verify(Path(args.verify)) else 1
    backup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
