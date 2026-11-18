"""Report the image coverage of every dictionary entry.

Unlike the enrichment report (which only knew about rows that got a photograph),
this reads the database itself, so it reflects what the app will actually show:
every entry resolves to either a real photograph or its category illustration.

Two files are written:

* ``image_coverage_entries.csv`` — one row per entry with the resolved image, its
  type (``photograph`` or ``illustration``), licence, author and asset path.
* ``image_coverage_summary.csv`` — totals by image type, category and licence.

The app's own lookup is replicated exactly (``status='approved'``,
``asset_status='approved'``, non-empty ``thumb_asset``, lowest ``rank`` first), so a
row appearing here means the card renders a picture for that entry.

Usage:
    python tools/build_image_coverage_report.py
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import Counter
from pathlib import Path

LOOKUP = """
SELECT e.entry_id, e.simplified, e.traditional, e.category,
       COALESCE(e.freq_rank, 999999) AS freq_rank,
       i.image_id, i.title, i.thumb_asset, i.license, i.author,
       i.source, i.source_url, i.attribution_text,
       ei.match_method, ei.rank AS image_rank
FROM entries e
JOIN entry_images ei ON ei.entry_id = e.entry_id
JOIN images i ON i.image_id = ei.image_id
WHERE i.status = 'approved'
  AND COALESCE(i.asset_status, 'approved') = 'approved'
  AND i.thumb_asset IS NOT NULL AND i.thumb_asset != ''
  AND ei.rank = (
      SELECT MIN(ei2.rank) FROM entry_images ei2
      JOIN images i2 ON i2.image_id = ei2.image_id
      WHERE ei2.entry_id = e.entry_id
        AND i2.status = 'approved'
        AND COALESCE(i2.asset_status, 'approved') = 'approved'
        AND i2.thumb_asset IS NOT NULL AND i2.thumb_asset != ''
  )
"""

COLUMNS = [
    "entry_id", "word", "traditional", "category", "freq_rank", "image_type",
    "image_id", "title", "licence", "author", "source", "source_url", "asset_path",
    "match_method", "attribution",
]


def image_type(source: str, match_method: str) -> str:
    if match_method == "category-fallback" or source == "project_illustration":
        return "illustration"
    return "photograph"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/build/dictionary.sqlite"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/build/reports"))
    args = parser.parse_args(argv[1:])

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(LOOKUP).fetchall()
    total_entries = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    con.close()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    # A few entries carried two images at the same winning rank; keep the first
    # so the report has exactly one row per entry and the totals reconcile.
    seen: set[int] = set()
    for row in rows:
        if row["entry_id"] in seen:
            continue
        seen.add(row["entry_id"])
        records.append({
            "entry_id": row["entry_id"],
            "word": row["simplified"],
            "traditional": row["traditional"],
            "category": row["category"],
            "freq_rank": row["freq_rank"],
            "image_type": image_type(row["source"] or "", row["match_method"] or ""),
            "image_id": row["image_id"],
            "title": row["title"],
            "licence": row["license"],
            "author": row["author"],
            "source": row["source"],
            "source_url": row["source_url"],
            "asset_path": row["thumb_asset"],
            "match_method": row["match_method"],
            "attribution": row["attribution_text"],
        })

    entries_path = args.out_dir / "image_coverage_entries.csv"
    with entries_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(records)

    summary: list[tuple[str, str, int]] = []
    for field, label in (("image_type", "image type"), ("category", "category"),
                         ("licence", "licence")):
        for value, count in Counter(str(r[field] or "(unknown)") for r in records).most_common():
            summary.append((label, value, count))
    summary_path = args.out_dir / "image_coverage_summary.csv"
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dimension", "value", "entries"])
        writer.writerows(summary)

    covered = len(records)
    photos = sum(1 for r in records if r["image_type"] == "photograph")
    print(f"entries total: {total_entries}")
    print(f"entries with a rendered image: {covered} ({100 * covered / total_entries:.1f}%)")
    print(f"  photographs: {photos}")
    print(f"  illustrations: {covered - photos}")
    print(f"entries with no image: {total_entries - covered}")
    print(f"written: {entries_path}")
    print(f"written: {summary_path}")
    return 0 if covered == total_entries else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
