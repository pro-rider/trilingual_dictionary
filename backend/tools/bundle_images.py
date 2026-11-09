"""Stage approved thumbnails into the Flutter asset tree and refresh the packaged DB.

Two outputs:
  1. `<app>/assets/images/thumbs/<xx>/<sha>.webp` — the exact paths stored in
     `images.thumb_asset`, so `Image.asset(path)` resolves inside the APK.
  2. `<app>/assets/data/dictionary.sqlite.gz` — the dictionary re-packed with the
     new image rows (only file rows change; text tables are untouched).

The Flutter side compares `meta.schema_version`/`dataset_version` through
`OfflineDictionary.assetVersion`, which must be bumped by hand after this runs —
the script prints the value to use.

Usage (from backend/):
  .\.venv\Scripts\python.exe tools\bundle_images.py --db data\build\dictionary.sqlite
"""

from __future__ import annotations

import argparse
import gzip
import re
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Rows from the old title-matching pipeline have no thumbnail and no verified
# concept; they must not reach the app as "approved".
NOISE = re.compile(
    r"(logo|coat of arms|seal|plaque|manuscript|title page|frontispiece|"
    r"engraving|libretto|woodcut|sheet music)", re.I)


def demote(con: sqlite3.Connection) -> dict[str, int]:
    """Demote anything that cannot be shown honestly in the app."""
    out: dict[str, int] = {}
    cur = con.execute(
        "UPDATE images SET asset_status = 'pending_review', "
        "verification_status = 'unverified' "
        "WHERE thumb_asset IS NULL OR thumb_asset = '' OR thumb_path IS NULL")
    out["no_thumbnail"] = cur.rowcount
    rows = con.execute("SELECT image_id, title FROM images "
                       "WHERE COALESCE(asset_status,'approved')='approved'").fetchall()
    bad = [r[0] for r in rows if NOISE.search(r[1] or "")]
    for image_id in bad:
        con.execute("UPDATE images SET asset_status='pending_review', "
                    "verification_status='unverified' WHERE image_id=?",
                    (image_id,))
    out["noise_title"] = len(bad)
    con.commit()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/build/dictionary.sqlite")
    ap.add_argument("--app", default=str(ROOT))
    ap.add_argument("--max-bytes", type=int, default=0,
                    help="stop adding thumbs once the asset tree passes this size")
    args = ap.parse_args()

    db = Path(args.db)
    app = Path(args.app)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    print("demoted:", demote(con))

    rows = con.execute(
        "SELECT image_id, sha256, thumb_path, thumb_asset, thumb_bytes "
        "FROM images WHERE COALESCE(asset_status,'approved') = 'approved' "
        "  AND thumb_path IS NOT NULL AND thumb_asset IS NOT NULL "
        "ORDER BY image_id"
    ).fetchall()
    print(f"approved image rows: {len(rows)}")

    dest_root = app / "assets" / "images" / "thumbs"
    dest_root.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    total = 0
    for row in rows:
        src = Path(row["thumb_path"])
        if not src.is_absolute():
            src = (db.parent.parent.parent / row["thumb_path"]).resolve()
        if not src.exists():
            skipped += 1
            continue
        rel = row["thumb_asset"].replace("assets/images/thumbs/", "")
        dest = dest_root / rel
        if args.max_bytes and total + (row["thumb_bytes"] or 0) > args.max_bytes:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
        total += row["thumb_bytes"] or dest.stat().st_size

    print(f"copied {copied} thumbs ({skipped} missing source files), "
          f"{total/1024.0:.1f} KB total")

    # Re-pack the dictionary so the APK carries the new image rows.
    gz_path = app / "assets" / "data" / "dictionary.sqlite.gz"
    with open(db, "rb") as src, gzip.open(gz_path, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)
    print(f"packed {gz_path} -> {gz_path.stat().st_size/1_000_000:.1f} MB")

    counts = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("images", "entry_images", "concepts", "examples")
    }
    print("row counts:", counts)
    print("next: bump OfflineDictionary.assetVersion in "
          "lib/data/local/offline_dictionary.dart, then flutter build apk")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
