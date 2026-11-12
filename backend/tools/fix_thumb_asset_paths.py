"""Flatten thumbnail asset paths so every declared asset is actually bundled.

`pubspec.yaml` declares `assets/images/thumbs/` non-recursively, so a thumbnail
stored in a subdirectory is never bundled into the APK and can never load.
This tool moves any such file to the flat directory, updates `images.thumb_asset`
in the database, and reports what it changed. Idempotent.

    python tools/fix_thumb_asset_paths.py --dry-run
    python tools/fix_thumb_asset_paths.py
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB = REPO_ROOT / "backend" / "data" / "build" / "dictionary.sqlite"
THUMB_DIR = REPO_ROOT / "assets" / "images" / "thumbs"
PREFIX = "assets/images/thumbs/"


def plan(con: sqlite3.Connection) -> list[tuple[int, str, str, Path, Path]]:
    rows = con.execute(
        "SELECT image_id, thumb_asset FROM images "
        "WHERE thumb_asset IS NOT NULL AND thumb_asset != ''"
    ).fetchall()
    todo = []
    for image_id, asset in rows:
        if not asset.startswith(PREFIX):
            continue
        relative = asset[len(PREFIX) :]
        if "/" not in relative:
            continue
        src = THUMB_DIR / relative.replace("/", "\\")
        dst = THUMB_DIR / relative.split("/")[-1]
        todo.append((image_id, asset, PREFIX + dst.name, src, dst))
    return todo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(DB)
    todo = plan(con)
    if not todo:
        print("nothing to fix: every thumb_asset lives in the declared directory")
        return 0

    for image_id, old, new, src, dst in todo:
        print(f"image_id {image_id}: {old} -> {new}")
        if not src.exists():
            print(f"  SKIP: source file missing on disk ({src})", file=sys.stderr)
            continue
        if args.dry_run:
            continue
        if dst.exists():
            print(f"  target already exists, keeping it ({dst.name})")
        else:
            shutil.copy2(src, dst)
        src.unlink()
        parent = src.parent
        if parent != THUMB_DIR and not any(parent.iterdir()):
            parent.rmdir()
        con.execute(
            "UPDATE images SET thumb_asset=? WHERE image_id=?", (new, image_id)
        )
        con.commit()

    print(f"{'would fix' if args.dry_run else 'fixed'} {len(todo)} row(s)")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
