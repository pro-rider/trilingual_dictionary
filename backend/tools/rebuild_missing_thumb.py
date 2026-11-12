"""Rebuild a missing bundled thumbnail from the row's own licensed source URL.

Only touches images whose `asset_status` is `missing` and whose `thumb_asset`
file does not exist. Downloads the image from `detail_url` (the recorded
Wikimedia Commons URL), re-encodes a WebP thumbnail in the flat thumb
directory, then updates the row. Never invents a picture: if the download
fails, the row is left exactly as it was and the failure is reported.

    python tools/rebuild_missing_thumb.py --dry-run
    python tools/rebuild_missing_thumb.py
"""
from __future__ import annotations

import argparse
import io
import sqlite3
import urllib.request
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
DB = REPO_ROOT / "backend" / "data" / "build" / "dictionary.sqlite"
THUMB_DIR = REPO_ROOT / "assets" / "images" / "thumbs"
MAX_EDGE = 320
QUALITY = 78
UA = "trilingual-dictionary-asset-build/1.0 (offline dictionary project)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT image_id, thumb_asset, detail_url, title FROM images "
        "WHERE asset_status='missing'"
    ).fetchall()
    if not rows:
        print("no rows marked missing")
        return 0

    failures = 0
    for image_id, asset, url, title in rows:
        target = (REPO_ROOT / (asset or "")).resolve()
        if asset and target.exists():
            print(f"image_id {image_id}: file already present, nothing to do")
            continue
        if not url:
            print(f"image_id {image_id}: no detail_url recorded, cannot rebuild")
            failures += 1
            continue
        flat_name = Path(asset or f"thumbs/{image_id}.webp").name
        dst = THUMB_DIR / flat_name
        print(f"image_id {image_id}: download -> {dst.relative_to(REPO_ROOT)}")
        if args.dry_run:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
            img = Image.open(io.BytesIO(raw))
            img.thumbnail((MAX_EDGE, MAX_EDGE))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            dst.parent.mkdir(parents=True, exist_ok=True)
            img.save(dst, format="WEBP", quality=QUALITY, method=4)
        except Exception as exc:
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        rel = dst.relative_to(REPO_ROOT).as_posix()
        con.execute(
            "UPDATE images SET thumb_asset=?, asset_status='approved', "
            "verification_status='verified', thumb_bytes=? WHERE image_id=?",
            (rel, dst.stat().st_size, image_id),
        )
        con.commit()
        print(f"  wrote {dst.stat().st_size} bytes, thumb_asset={rel}")

    con.close()
    print(f"failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
