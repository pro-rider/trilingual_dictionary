"""Flatten thumbnail paths so every asset sits directly in
`assets/images/thumbs/`.

Flutter's `pubspec.yaml` entry `- assets/images/thumbs/` bundles only the files
**in that directory**, not its subdirectories. A row pointing at
`assets/images/thumbs/39/39d0….webp` would therefore render as a broken image
inside the APK even though the file exists on disk. Older rows produced by an
earlier script used that nested layout, so they are rewritten here to
`assets/images/thumbs/<basename>` and the file is copied flat.

Usage: python tools/flatten_thumbs.py [--dry-run]
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "build" / "dictionary.sqlite"
THUMB_DIR = ROOT.parent / "assets" / "images" / "thumbs"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT image_id, thumb_asset FROM images WHERE thumb_asset IS NOT NULL"
    ).fetchall()
    moved = missing = already = 0
    for image_id, rel in rows:
        rel = (rel or "").strip()
        if not rel:
            continue
        path = ROOT.parent / rel
        name = Path(rel).name
        target_rel = f"assets/images/thumbs/{name}"
        if path.parent == THUMB_DIR and path.exists():
            already += 1
            continue
        if not path.exists():
            if not args.dry_run:
                con.execute("UPDATE images SET asset_status='missing' WHERE image_id=?",
                            (image_id,))
            missing += 1
            continue
        flat = THUMB_DIR / name
        if not args.dry_run:
            THUMB_DIR.mkdir(parents=True, exist_ok=True)
            if not flat.exists():
                shutil.copy2(path, flat)
            con.execute("UPDATE images SET thumb_asset=? WHERE image_id=?",
                        (target_rel, image_id))
        moved += 1
    if not args.dry_run:
        con.commit()
    print(f"flat={already} moved={moved} missing={missing} total={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
