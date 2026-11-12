"""Remove image rows that failed review, with their thumbnails.

Used to roll back an acquisition run whose matches were wrong. Deletes exactly:
  - the `images` rows in the given id range,
  - their `entry_images` and `concept_images` rows,
  - `concepts` rows left with no image,
  - the WebP files those rows referenced (inside assets/images/thumbs only).

`--dry-run` prints the plan; `--from-id` keeps the cut-off explicit so an
accidental wide delete is impossible.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "backend" / "data" / "build" / "dictionary.sqlite"
THUMB_ROOT = (REPO / "assets" / "images" / "thumbs").resolve()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-id", type=int, required=True)
    ap.add_argument("--to-id", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    sql = "SELECT image_id, thumb_asset, title FROM images WHERE image_id >= ?"
    params: list = [args.from_id]
    if args.to_id is not None:
        sql += " AND image_id <= ?"
        params.append(args.to_id)
    rows = con.execute(sql + " ORDER BY image_id", params).fetchall()

    print(f"range {args.from_id}..{args.to_id or 'max'} — {len(rows)} row(s)")
    files: list[Path] = []
    for row in rows:
        print(f"  {row['image_id']:>4}  {row['title'][:52]}")
        asset = (row["thumb_asset"] or "").strip()
        if asset.startswith("assets/images/thumbs/"):
            path = (REPO / asset).resolve()
            if path.is_file() and THUMB_ROOT in path.parents:
                files.append(path)

    if args.dry_run:
        print(f"would delete {len(rows)} row(s) and {len(files)} file(s)")
        con.close()
        return 0

    ids = [row["image_id"] for row in rows]
    if not ids:
        con.close()
        return 0
    marks = ",".join("?" * len(ids))
    con.execute(f"DELETE FROM entry_images WHERE image_id IN ({marks})", ids)
    con.execute(f"DELETE FROM concept_images WHERE image_id IN ({marks})", ids)
    con.execute(f"DELETE FROM images WHERE image_id IN ({marks})", ids)
    con.execute(
        "DELETE FROM concepts WHERE concept_id NOT IN "
        "(SELECT concept_id FROM concept_images) AND concept_id NOT IN "
        "(SELECT concept_id FROM entry_concepts WHERE concept_id IS NOT NULL)")
    con.commit()

    removed = 0
    for path in files:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            print(f"  file not removed: {path} ({exc})")

    print(f"deleted {len(ids)} row(s), {removed} file(s)")
    print("images now:", con.execute("SELECT COUNT(*) FROM images").fetchone()[0])
    print("entry_images now:", con.execute("SELECT COUNT(*) FROM entry_images").fetchone()[0])
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
