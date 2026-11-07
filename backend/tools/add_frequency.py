"""Fill ``entries.freq_rank`` from the open ``wordfreq`` corpus.

Why this exists
---------------
CC-CEDICT has no frequency data, so 123,672 entries were all equally "common":
searching "water" could return 溍 (a rare character glossed "water") before 水,
and "book" returned 册 before 书. Ranking needs a real usage signal.

``wordfreq`` (MIT, https://github.com/rspeer/wordfreq) ships precomputed
Chinese frequencies from several corpora; ``zipf_frequency`` is a log scale
where 7 ≈ "the", 4 ≈ "uncommon but real", <2 ≈ "vanishingly rare".

Rank 1 = most frequent. Words absent from every corpus keep NULL, which the
lookup treats as "unknown, sort last".

Usage
-----
    .venv\\Scripts\\python.exe tools/add_frequency.py --db data\\build\\dictionary.sqlite
    .venv\\Scripts\\python.exe tools/add_frequency.py --db ... --report freq.report.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

from wordfreq import zipf_frequency


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/build/dictionary.sqlite")
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    path = Path(args.db)
    if not path.exists():
        print(f"missing database: {path}")
        return 1

    started = time.time()
    con = sqlite3.connect(path)
    con.execute("CREATE INDEX IF NOT EXISTS idx_entries_freq ON entries(freq_rank)")

    words = [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT simplified FROM entries"
        ).fetchall()
    ]
    print(f"scoring {len(words)} distinct headwords ...")

    scores: dict[str, float] = {}
    for w in words:
        scores[w] = zipf_frequency(w, "zh")

    ranked = sorted(words, key=lambda w: (-scores[w], w))
    updates = []
    known = 0
    for rank, w in enumerate(ranked, start=1):
        if scores[w] <= 0.0:
            continue  # absent from every corpus -> NULL, not a fake rank
        updates.append((rank, w))
        known += 1

    con.executemany(
        "UPDATE entries SET freq_rank = ? WHERE simplified = ?", updates
    )
    con.commit()

    row = con.execute(
        "SELECT COUNT(*) FROM entries WHERE freq_rank IS NOT NULL"
    ).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    top = con.execute(
        "SELECT simplified, freq_rank FROM entries "
        "WHERE freq_rank IS NOT NULL ORDER BY freq_rank LIMIT 10"
    ).fetchall()
    con.close()

    elapsed = time.time() - started
    summary = {
        "entries": total,
        "with_freq_rank": row,
        "distinct_headwords": len(words),
        "scored": known,
        "elapsed_s": round(elapsed, 1),
        "top10": [{"word": w, "rank": r} for w, r in top],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.report:
        Path(args.report).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
