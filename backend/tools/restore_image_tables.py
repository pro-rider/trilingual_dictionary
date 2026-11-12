"""Restore the image tables from a backup after an over-wide prune.

Copies only `images`, `entry_images`, `concept_images` and `concepts` — the
staging tables and everything else in the working database stay as they are. The
column list is read from the backup so a schema drift cannot silently mismatch.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "build" / "dictionary.sqlite"
BACKUPS = Path(__file__).resolve().parents[1] / "data" / "build" / "backups"
TABLES = ("concepts", "images", "concept_images", "entry_images")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    backup = Path(args.backup) if args.backup else max(
        (p for p in BACKUPS.glob("dictionary.sqlite.bak-*")
         if not any(p.name.endswith(s) for s in ("-shm", "-wal", ".sha256"))),
        key=lambda p: p.stat().st_mtime)
    print(f"backup: {backup.name} ({backup.stat().st_size:,} B)")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safety = DB.with_name(f"dictionary.sqlite.pre-restore-{stamp}")
    if not args.dry_run:
        shutil.copy2(DB, safety)
        print(f"safety copy: {safety.name}")

    con = sqlite3.connect(DB)
    con.execute("ATTACH DATABASE ? AS bak", (str(backup).replace("\\", "/"),))
    for table in TABLES:
        cols = [r[1] for r in con.execute(f"PRAGMA bak.table_info({table})")]
        existing = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        shared = [c for c in cols if c in existing]
        missing = sorted(set(cols) - set(existing))
        count = con.execute(f"SELECT COUNT(*) FROM bak.{table}").fetchone()[0]
        print(f"{table:16} backup rows {count:>6}  columns shared {len(shared)}"
              + (f"  (ignored: {missing})" if missing else ""))
        if args.dry_run:
            continue
        con.execute(f"DELETE FROM {table}")
        collist = ",".join(f'"{c}"' for c in shared)
        con.execute(f"INSERT INTO {table}({collist}) SELECT {collist} FROM bak.{table}")

    if not args.dry_run:
        con.commit()
        for table in TABLES:
            print(f"{table:16} now {con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:>6}")
    con.execute("DETACH DATABASE bak")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
