"""Generate the bundled thumbnail for approved images that lack one.

`image 7` (a CC BY-SA 4.0 photograph of a bus) had a 256 px JPEG sitting in
`data/images/` but no `thumb_asset`, so the client's filter dropped it and the two
words it belongs to (公共汽车 / 公车) showed the placeholder. The licence, author
and attribution were all present; only the WebP step was missing.

This tool never invents metadata and never downloads: it reads the local JPEG/PNG
already on disk, writes a <=15 KB WebP under `assets/images/thumbs/<hash>.webp`
with the same naming scheme the pipeline uses, and records the path.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "backend" / "data" / "build" / "dictionary.sqlite"
THUMBS = REPO / "assets" / "images" / "thumbs"
THUMB_MAX_BYTES = 15_000


def make_thumb(path: Path) -> bytes:
    img = Image.open(path).convert("RGB")
    for width in (200, 160, 120):
        scale = width / float(img.width)
        height = max(1, int(round(img.height * scale)))
        resized = img.resize((width, height), Image.LANCZOS)
        for quality in range(80, 39, -10):
            buf = io.BytesIO()
            resized.save(buf, format="WEBP", quality=quality, method=6)
            if buf.tell() <= THUMB_MAX_BYTES:
                return buf.getvalue()
    raise ValueError("thumbnail cannot meet the 15 KB ceiling")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db if hasattr(args, "db") else DB, timeout=20)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        "SELECT image_id, content_hash, sha256, thumb_path, detail_path, "
        "       status, asset_status, license, author, title "
        "FROM images WHERE (thumb_asset IS NULL OR thumb_asset = '') "
        "ORDER BY image_id").fetchall()

    fixed = 0
    for row in rows:
        if row["status"] != "approved":
            continue
        if not row["license"] or not row["author"]:
            print(f"skip image {row['image_id']}: licence or author missing "
                  f"(cannot approve without attribution)")
            continue
        sources = [row["thumb_path"], row["detail_path"]]
        src = None
        for candidate in sources:
            if not candidate:
                continue
            for base in (Path.cwd(), REPO / "backend"):
                p = base / candidate if not Path(candidate).is_absolute() else Path(candidate)
                if p.is_file():
                    src = p
                    break
            if src:
                break
        if src is None:
            print(f"skip image {row['image_id']}: no local source file "
                  f"({row['thumb_path']})")
            continue

        blob = make_thumb(src)
        key = (row["sha256"] or row["content_hash"] or "").strip()
        if not key:
            key = hashlib.sha256(src.read_bytes()).hexdigest()
        sub = key[:2]
        rel = f"assets/images/thumbs/{sub}/{key}.webp"
        dest = REPO / rel
        print(f"image {row['image_id']} ({row['title'][:38]}): {src.name} -> {rel} "
              f"({len(blob)} B)")
        if args.dry_run:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        con.execute(
            "UPDATE images SET thumb_asset=?, asset_status='approved', "
            "thumb_bytes=?, sha256=COALESCE(sha256, ?) WHERE image_id=?",
            (rel, len(blob), key if len(key) == 64 else None, row["image_id"]))
        fixed += 1

    if not args.dry_run:
        con.commit()
    print(f"\n{'would fix' if args.dry_run else 'fixed'} {fixed} image(s)")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
