"""Read-only probe: image columns/tables, example coverage, network reachability."""

from __future__ import annotations

import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "build" / "dictionary.sqlite"


def main() -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print("db:", DB, DB.stat().st_size, "bytes")

    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print("tables:", tables)

    print("entries cols:", [r["name"] for r in con.execute("PRAGMA table_info(entries)")])
    total = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    print("entries count:", total)

    print("examples count:", con.execute("SELECT COUNT(*) FROM examples").fetchone()[0])
    print("examples cols:", [r["name"] for r in con.execute("PRAGMA table_info(examples)")])
    have = con.execute(
        "SELECT COUNT(DISTINCT s.entry_id) FROM examples ex "
        "JOIN senses s ON s.sense_id = ex.sense_id").fetchone()[0]
    print("entries_with_examples:", have, "pct: %.2f%%" % (100.0 * have / total))

    for t in ("images", "entry_images"):
        print(t, "cols:", [r["name"] for r in con.execute(f"PRAGMA table_info({t})")])
        print(t, "rows:", con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])

    hits = []
    for t in tables:
        for r in con.execute(f"PRAGMA table_info({t})"):
            if any(k in r["name"].lower() for k in ("image", "photo", "thumb", "picture")):
                hits.append((t, r["name"]))
    print("image-ish columns:", hits or "NONE")

    print("meta:", [tuple(r) for r in con.execute("SELECT key, value FROM meta")])
    print("indexes:", [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name")])

    # which entries do have examples, and in what shape
    print("example rows sample:",
          [tuple(r) for r in con.execute(
              "SELECT * FROM examples LIMIT 3")])
    con.close()

    for mod in ("PIL", "imagehash", "requests", "httpx"):
        try:
            __import__(mod)
            print("pkg", mod, "OK")
        except Exception as exc:  # noqa: BLE001
            print("pkg", mod, "MISSING", type(exc).__name__)

    req = urllib.request.Request(
        "https://commons.wikimedia.org/w/api.php?action=query&format=json&titles=File:Mountain.jpg",
        headers={"User-Agent": "TrilingualDictionary/0.1 (probe)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print("wikimedia api status:", resp.status, "len:", len(resp.read()))
    except Exception as exc:  # noqa: BLE001
        print("wikimedia api FAILED:", type(exc).__name__, exc)

    req2 = urllib.request.Request(
        "https://www.wikidata.org/w/api.php?action=wbsearchentities&search=mountain&language=en&format=json&limit=3",
        headers={"User-Agent": "TrilingualDictionary/0.1 (probe)"})
    try:
        with urllib.request.urlopen(req2, timeout=20) as resp:
            print("wikidata api status:", resp.status, "len:", len(resp.read()))
    except Exception as exc:  # noqa: BLE001
        print("wikidata api FAILED:", type(exc).__name__, exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
