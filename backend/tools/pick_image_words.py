"""Build the acquisition work list and split it across parallel workers."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from images_v2 import PICTABLE_CATEGORIES, candidate_rows  # noqa: E402

DB = Path(__file__).resolve().parents[1] / "data" / "build" / "dictionary.sqlite"
OUT = Path(__file__).resolve().parents[1] / "data" / "build" / "words"
CONCRETE = ["nature", "everyday", "transport", "tools_instruments",
            "science_medicine", "technology", "geography_environment", "business"]


def main(count: int = 1200, workers: int = 4) -> int:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    done = {r[0] for r in con.execute("SELECT DISTINCT entry_id FROM entry_images")}
    rows = candidate_rows(con, count, done, CONCRETE, None, True)
    words = [r["simplified"] for r in rows]
    con.close()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "all.txt").write_text("\n".join(words), encoding="utf-8")
    for i in range(workers):
        chunk = words[i::workers]
        (OUT / f"batch{i + 1}.txt").write_text("\n".join(chunk), encoding="utf-8")
    print(f"{len(words)} candidate words -> {workers} worker lists in {OUT}")
    print(f"first 15: {', '.join(words[:15])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
