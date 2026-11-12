"""Re-take the shipped-database pin after the last write to the working DB.

The guard test compares a pinned sha256 with the file on disk. Any tool that
opens the working database read-write rewrites pages, so the pin must be taken
as the very last step of a session — that is what this script exists for. It
refuses to run while another process holds the file (a live WAL is fine, a
locked writer is not).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tools import build_release_db as brel  # noqa: E402


def main() -> int:
    db = brel.WORKING_DB
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if integrity != "ok":
        raise SystemExit(f"refusing to pin a database that fails integrity_check: {integrity}")

    release = json.loads(brel.RELEASE_JSON.read_text(encoding="utf-8"))
    counts = release["counts"]
    sha = brel.sha256_file(db)
    size = db.stat().st_size
    brel.repin(sha, size, release["asset_version"], counts)
    print(f"pinned {sha}  {size:,} bytes  ({release['asset_version']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
