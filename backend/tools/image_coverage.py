"""Coverage on the words people actually look up: top-N frequency bands.

A single 0.165% headline hides the number that matters. This prints, for each
frequency band, how many entries exist, how many can show a bundled picture, and
what share of lookups that represents (frequency-weighted, using the same
freq_rank ordering the app sorts by).
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "build" / "dictionary.sqlite"
BANDS = (500, 1000, 2000, 3000, 5000, 10000, 20000)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args(argv)

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    total = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    have = con.execute("SELECT COUNT(DISTINCT entry_id) FROM entry_images").fetchone()[0]
    print(f"all entries           {total:>7,}   with a picture {have:>6,}   "
          f"{100.0 * have / total:5.2f}%")
    print()
    print(f"{'band':>10}  {'entries':>8}  {'with pic':>9}  {'coverage':>9}  {'band gain':>9}")
    prev_band = 0
    prev_have = 0
    for band in BANDS:
        entries = con.execute(
            "SELECT COUNT(*) FROM entries WHERE freq_rank IS NOT NULL AND freq_rank <= ?",
            (band,)).fetchone()[0]
        pics = con.execute(
            "SELECT COUNT(DISTINCT e.entry_id) FROM entries e "
            "JOIN entry_images ei ON ei.entry_id = e.entry_id "
            "WHERE e.freq_rank IS NOT NULL AND e.freq_rank <= ?", (band,)).fetchone()[0]
        inside = con.execute(
            "SELECT COUNT(DISTINCT e.entry_id) FROM entries e "
            "JOIN entry_images ei ON ei.entry_id = e.entry_id "
            "WHERE e.freq_rank IS NOT NULL AND e.freq_rank > ? AND e.freq_rank <= ?",
            (prev_band, band)).fetchone()[0]
        inside_total = entries - con.execute(
            "SELECT COUNT(*) FROM entries WHERE freq_rank IS NOT NULL AND freq_rank <= ?",
            (prev_band,)).fetchone()[0]
        share = 100.0 * pics / entries if entries else 0.0
        edge = (100.0 * inside / inside_total) if inside_total else 0.0
        print(f"top {band:>6,}  {entries:>8,}  {pics:>9,}  {share:>8.2f}%  {edge:>8.2f}%")
        prev_band, prev_have = band, pics
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
