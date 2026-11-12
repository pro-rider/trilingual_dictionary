"""Compare a freshly built release DB with the approved shipped asset by CONTENT.

The shipped asset is pinned and approved (db-8b0db9597b). A later write to the
working database — staging rows that the release build drops — regenerates the
release DB with different *bytes* but identical *content*. This tool proves which
of those two situations it is, so the approved asset is not replaced for nothing.

    python tools/compare_release_content.py <fresh.sqlite>
"""

from __future__ import annotations

import gzip
import hashlib
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKED = REPO / "assets" / "data" / "dictionary.sqlite.gz"


def digest(con: sqlite3.Connection) -> dict[str, tuple[int, str]]:
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE '%_data' AND name NOT LIKE '%_idx' AND name NOT LIKE '%_content' "
        "AND name NOT LIKE '%_docsize' AND name NOT LIKE '%_config' ORDER BY name")]
    out = {}
    for table in tables:
        rows = con.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        payload = "\x1f".join("\x1e".join("" if v is None else str(v) for v in row)
                              for row in rows)
        out[table] = (len(rows), hashlib.sha256(payload.encode()).hexdigest()[:16])
    return out


def main(argv: list[str]) -> int:
    fresh = Path(argv[1])
    shipped = Path(tempfile.mkdtemp()) / "shipped.sqlite"
    with gzip.open(PACKED, "rb") as src, open(shipped, "wb") as dst:
        dst.write(src.read())

    a = digest(sqlite3.connect(f"file:{fresh}?mode=ro", uri=True))
    b = digest(sqlite3.connect(f"file:{shipped}?mode=ro", uri=True))

    same = a == b
    for table in sorted(set(a) | set(b)):
        left, right = a.get(table), b.get(table)
        flag = "" if left == right else "   <-- DIFFERS"
        print(f"  {table:24} fresh={left} shipped={right}{flag}")
    print("\nCONTENT IDENTICAL — the shipped asset is still correct" if same
          else "\nCONTENT DIFFERS — the asset must be rebuilt and re-approved")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
