"""Phase 2 — fail the build when an image reference cannot be rendered.

Four failure modes are invisible at runtime because the Flutter card turns every
one of them into the same grey placeholder:

  1. `thumb_asset` names a file that is not in the bundle;
  2. `thumb_asset` uses a nested path (`thumbs/ab/ab….webp`) — the file exists,
     but `pubspec.yaml` declares one directory and Flutter bundles only its files,
     so the entry point never reaches the APK;
  3. a thumbnail sits in the bundle that no row points at (dead weight, and a
     leftover from a database that no longer ships);
  4. an image is `status='approved'` but has no `thumb_asset` at all, so the
     client's own filter silently drops it.

Exit code 1 with a non-empty failure list. `--fix` regenerates the one recoverable
case (a thumbnail that exists on disk but was never recorded in `thumb_asset`),
and nothing else: a missing source image is never invented.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "backend" / "data" / "build" / "dictionary.sqlite"
THUMBS = REPO / "assets" / "images" / "thumbs"
PACKED_DETAIL = REPO / "backend" / "data" / "images"
PREFIX = "assets/images/thumbs/"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--thumbs", default=str(THUMBS))
    ap.add_argument("--fix", action="store_true",
                    help="record thumb_asset for files that exist on disk")
    args = ap.parse_args(argv)

    thumbs = Path(args.thumbs)
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        "SELECT image_id, thumb_asset, thumb_path, status, asset_status, title "
        "FROM images ORDER BY image_id").fetchall()

    on_disk = {p.relative_to(thumbs.parents[2]).as_posix(): p
               for p in thumbs.rglob("*") if p.is_file()}
    referenced: set[str] = set()
    failures: list[str] = []
    warnings: list[str] = []

    for row in rows:
        asset = (row["thumb_asset"] or "").strip()
        approved = row["status"] == "approved"
        if not asset:
            if approved and (row["asset_status"] or "") == "approved":
                failures.append(
                    f"image {row['image_id']} is approved with no thumb_asset "
                    f"({(row['title'] or '')[:40]})")
            else:
                warnings.append(
                    f"image {row['image_id']} has no thumbnail "
                    f"(status={row['status']}, asset_status={row['asset_status']})")
            continue
        if not asset.startswith(PREFIX):
            failures.append(
                f"image {row['image_id']} thumb_asset outside the bundled root: {asset}")
            continue
        if "/" in asset[len(PREFIX):]:
            # Flutter bundles the *files* of the declared directory; a nested path
            # is on disk but absent from the APK, which the card renders as the
            # same grey placeholder as a genuinely missing picture.
            failures.append(
                f"image {row['image_id']} thumb_asset is nested and will not be "
                f"bundled (run tools/flatten_thumbs.py): {asset}")
            referenced.add(asset)
            continue
        referenced.add(asset)
        if not (REPO / asset).is_file():
            failures.append(
                f"image {row['image_id']} thumb_asset missing on disk: {asset}")

    orphans = sorted(set(on_disk) - referenced)
    for path in orphans:
        failures.append(f"orphan thumbnail not referenced by any row: {path}")

    # a vanished detail file only matters for the "tap to enlarge" dialog
    missing_detail = 0
    for row in rows:
        detail = (row["thumb_path"] or "").strip()
        if detail and "data/images" in detail and not Path(detail).is_file() and not (
                REPO / detail).is_file():
            missing_detail += 1

    if args.fix:
        fixed = 0
        for row in rows:
            if (row["thumb_asset"] or "").strip():
                continue
            sha = (row["content_hash"] or "").strip()
            if not sha:
                continue
            sub = sha[:2]
            candidate = f"{PREFIX}{sub}/{sha}.webp"
            if (REPO / candidate).is_file():
                con.execute("UPDATE images SET thumb_asset=?, asset_status='approved' "
                            "WHERE image_id=?", (candidate, row["image_id"]))
                fixed += 1
        con.commit()
        print(f"recorded {fixed} thumbnail path(s) that already existed on disk")

    print(f"images                 {len(rows)}")
    print(f"referenced thumbnails  {len(referenced)}")
    print(f"files under thumbs/    {len(on_disk)}")
    print(f"orphans                {len(orphans)}")
    print(f"missing detail files   {missing_detail}")
    print()
    for line in failures:
        print(f"FAIL  {line}")
    for line in warnings[:20]:
        print(f"warn  {line}")
    if len(warnings) > 20:
        print(f"warn  … {len(warnings) - 20} more")

    print()
    if failures:
        print(f"IMAGE ASSETS FAILED — {len(failures)} blocking problem(s)")
        con.close()
        return 1
    print("IMAGE ASSETS OK — every approved picture resolves to a bundled thumbnail")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
