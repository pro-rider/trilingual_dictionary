"""Repair the broken image paths using bytes already on disk.

Why this exists: 65 `images.thumb_path` / `detail_path` rows hold absolute build
machine paths (`C:/Users/<name>/Desktop/...`). `images.py::_relative`
strips only the `data/images/` prefix, so an absolute path is returned whole and
the public URL leaks the build machine's username and directory layout — and the
URL never resolves. Meanwhile the real bytes are sitting in the repo at
`assets/images/thumbs/<hash>.webp` (the ones bundled into the APK).

This tool copies those bytes into the server's image root, verifies the copy, and
rewrites the row to the canonical relative form:

    data/images/thumbs/<shard>/<sha256>.webp      (shard = first 2 hex chars)

No network, no cost, no generated content: it re-uses licensed bytes that already
ship with the app.

Usage (from the repo root, backend venv python):
    python backend/tools/repair_image_paths.py            # dry run, prints the plan
    python backend/tools/repair_image_paths.py --apply     # backup, copy, rewrite

Safety:
  * `--apply` writes a timestamped backup of dictionary.sqlite first and refuses
    to run if that backup cannot be verified by size.
  * Each copy is verified by sha256 against its source before the row is touched.
  * `docs/ASSET-PINS.json` is NOT modified here. The pin is an approval record
    (see the note inside the file); this tool prints the new hash for that step.
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
DB = REPO / "backend" / "data" / "build" / "dictionary.sqlite"
ROOT = REPO / "backend" / "data" / "images"
ASSETS = REPO / "assets" / "images" / "thumbs"
BACKUPS = REPO / "backend" / "data" / "build" / "backups"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def basename(path: str) -> str:
    return (path or "").replace("\\", "/").split("/")[-1]


def plan(con: sqlite3.Connection) -> dict:
    """Work out, row by row, what would change. Nothing is written here."""
    rows = con.execute(
        "SELECT image_id, thumb_path, detail_path, detail_url, sha256 FROM images"
    ).fetchall()
    copy: list[dict] = []      # bytes to place, then a row to rewrite
    unrepairable: list[dict] = []
    already_ok: list[dict] = []
    detail_to_clear: list[str] = []

    for r in rows:
        name = basename(r["thumb_path"])
        rel = f"data/images/thumbs/{name[:2]}/{name}" if name else ""
        dest = ROOT / "thumbs" / name[:2] / name if name else None
        if not name:
            unrepairable.append({"image_id": r["image_id"], "why": "empty thumb_path"})
            continue
        if dest is not None and dest.exists():
            # A later reader may still hold the absolute string; rewriting it is
            # idempotent and safe, so normalise the text even when bytes exist.
            already_ok.append({"image_id": r["image_id"], "path": rel})
            continue
        src = ASSETS / name
        if src.exists():
            copy.append({"image_id": r["image_id"], "name": name, "src": src,
                         "dest": dest, "rel": rel,
                         "src_sha": sha256(src)})
        else:
            unrepairable.append({"image_id": r["image_id"], "why": f"no bytes for {name}"})

        # detail_path: only keep it if the bytes really sit under the image root.
        # A path that merely exists somewhere else on disk (the asset copy) is
        # NOT servable by /static/images, so leaving it would build a broken URL.
        dp = (r["detail_path"] or "").strip().replace("\\", "/")
        if dp:
            dp_rel = dp.split("data/images/")[-1] if "data/images/" in dp else ""
            if not dp_rel or not (ROOT / dp_rel).exists():
                if (r["detail_url"] or "").strip().lower().startswith("http"):
                    detail_to_clear.append(r["image_id"])

    return {"rows": len(rows), "copy": copy, "unrepairable": unrepairable,
            "already_ok": already_ok, "detail_to_clear": detail_to_clear}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    if not DB.exists():
        print(f"BLOCKED: database not found at {DB}")
        return 2

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    p = plan(con)
    con.close()

    print(f"images rows                 {p['rows']}")
    print(f"bytes copyable (assets->root) {len(p['copy'])}")
    print(f"already resolvable           {len(p['already_ok'])}")
    print(f"unrepairable                 {len(p['unrepairable'])}")
    for u in p["unrepairable"][:5]:
        print(f"  - image {u['image_id']}: {u['why']}")
    print(f"detail_path rows to clear    {len(p['detail_to_clear'])}")

    if not args.apply:
        print("\nDRY RUN. Exact plan for --apply:")
        print("  1. backup  backend/data/build/backups/dictionary.<ts>.sqlite")
        print("  2. for each copyable row: copy asset -> backend/data/images/thumbs/ab/<sha256>.webp")
        print("     and verify sha256(copy) == sha256(source) before touching the row")
        print("  3. UPDATE images SET thumb_path = '<rel>' WHERE image_id = ?")
        print("  4. UPDATE images SET detail_path = NULL WHERE image_id IN (unresolvable)")
        print("  5. verify: every rewritten path exists under backend/data/images")
        print("  6. print the new dictionary.sqlite sha256 for the pin approval")
        return 0

    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUPS / f"dictionary.{stamp}.sqlite"
    shutil.copy2(DB, backup)
    if backup.stat().st_size != DB.stat().st_size:
        print(f"BLOCKED: backup size mismatch ({backup.stat().st_size} != {DB.stat().st_size})")
        return 2
    print(f"backup: {backup}  ({backup.stat().st_size:,} bytes)")

    placed = failed = 0
    for c in p["copy"]:
        c["dest"].parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(c["src"], c["dest"])
        if sha256(c["dest"]) != c["src_sha"]:
            print(f"  SKIP image {c['image_id']}: copy hash mismatch")
            failed += 1
            continue
        placed += 1

    con = sqlite3.connect(DB)
    try:
        for c in p["copy"]:
            if sha256(c["dest"]) != c["src_sha"]:
                continue
            con.execute("UPDATE images SET thumb_path = ? WHERE image_id = ?",
                        (c["rel"], c["image_id"]))
        for row in p["already_ok"]:
            dest = ROOT / "thumbs" / basename(row["path"])[:2] / basename(row["path"])
            if dest.exists():
                con.execute("UPDATE images SET thumb_path = ? WHERE image_id = ?",
                            (row["path"], row["image_id"]))
        for iid in p["detail_to_clear"]:
            con.execute("UPDATE images SET detail_path = NULL WHERE image_id = ?", (iid,))
        con.commit()
    finally:
        con.close()

    # verify every path the API would now build
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    bad = []
    for r in con.execute("SELECT image_id, thumb_path FROM images").fetchall():
        rel = (r[1] or "").replace("data/images/", "")
        if not rel or not (ROOT / rel).exists():
            bad.append((r[0], r[1]))
    con.close()

    print(f"copied+verified {placed}, copy failures {failed}")
    print(f"rows still without servable bytes: {len(bad)}")
    print(f"new dictionary.sqlite sha256: {sha256(DB)}")
    print("\nASSET-PINS.json is unchanged on purpose. Approve this hash explicitly,")
    print("then update docs/ASSET-PINS.json in its own commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
