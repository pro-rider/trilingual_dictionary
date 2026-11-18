"""Build the licence-cleared image report for the dictionary.

Reads the merged enrichment output (``image_gap_images.csv`` or the raw shard
outputs) and writes two deliverables plus a console summary:

* ``image_report_entries.csv`` — one row per entry that received an image, with
  the headword, English gloss, category, frequency rank, provider, licence,
  author and the Commons/Wikipedia source page. This is the auditable list.
* ``image_report_summary.csv`` — counts by licence, provider and category, so
  the totals can be checked without pivoting the entry list.

Only rows whose ``image_link`` is non-empty are reported: a blank row means no
licence-compliant candidate was found, and the report never guesses to fill it.

Usage:
    python tools/build_image_report.py --shards .cache/shards16
    python tools/build_image_report.py --input data/build/image_links/image_gap_images.csv
"""

from __future__ import annotations

import argparse
import csv
import glob
import sys
from collections import Counter
from pathlib import Path

ENTRY_COLUMNS = [
    "entry_id", "word", "category", "freq_rank", "gloss_en", "search_term",
    "image_provider", "image_licence", "image_creator", "image_link", "image_source_page",
]


def load_rows(shard_dir: Path | None, input_csv: Path | None) -> tuple[list[str], list[list[str]]]:
    if input_csv is not None:
        with input_csv.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        if not rows:
            raise SystemExit(f"{input_csv} is empty")
        return rows[0], rows[1:]

    shard_root = shard_dir or Path(".")
    # Earlier runs left other shard outputs beside the current ones; prefer the
    # gated set when it exists so the report never mixes two generations of rows.
    files = sorted(p for p in shard_root.glob("gated_*_out.csv"))
    if not files:
        files = sorted(p for p in shard_root.glob("shard_*_out.csv"))
    if not files:
        raise SystemExit(f"no shard outputs found in {shard_dir}")
    header: list[str] | None = None
    body: list[list[str]] = []
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            shard_header = next(reader, None)
            if shard_header is None:
                continue
            if header is None:
                header = shard_header
            elif shard_header != header:
                raise SystemExit(f"header mismatch in {path.name}")
            body.extend(row for row in reader if row)
    return header or [], body


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards", type=Path, help="directory holding *_out.csv shard results")
    parser.add_argument("--input", type=Path, help="single merged CSV instead of shards")
    parser.add_argument("--out-dir", type=Path, default=Path("data/build/reports"))
    args = parser.parse_args(argv[1:])
    if not args.shards and not args.input:
        parser.error("pass --shards or --input")

    header, body = load_rows(args.shards, args.input)
    for column in ("image_link", "image_licence", "image_provider"):
        if column not in header:
            raise SystemExit(f"missing column {column}; not an enrichment output")
    link_index = header.index("image_link")

    filled: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in body:
        if len(row) <= link_index or not row[link_index].strip():
            continue
        record = {column: (row[header.index(column)] if header.index(column) < len(row) else "")
                  for column in ENTRY_COLUMNS if column in header}
        key = record.get("entry_id") or record.get("word") or ""
        if key in seen:
            continue
        seen.add(key)
        filled.append(record)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    entries_path = args.out_dir / "image_report_entries.csv"
    with entries_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[c for c in ENTRY_COLUMNS if c in header])
        writer.writeheader()
        writer.writerows(filled)

    summary_rows: list[tuple[str, str, int]] = []
    for field, label in (("image_licence", "licence"), ("image_provider", "provider"),
                         ("category", "category")):
        for value, count in Counter(row.get(field) or "(unknown)" for row in filled).most_common():
            summary_rows.append((label, value, count))
    summary_path = args.out_dir / "image_report_summary.csv"
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dimension", "value", "entries"])
        writer.writerows(summary_rows)

    attempted = sum(1 for row in body if len(row) > link_index)
    total = len(body)
    print(f"entries with a licence-cleared image: {len(filled)} of {total} gap entries "
          f"({100 * len(filled) / total:.1f}% of the list)" if total else "no rows")
    for value, count in Counter(row.get("image_licence") for row in filled).most_common():
        print(f"  licence {value or '(unknown)':<14} {count}")
    print(f"written: {entries_path}")
    print(f"written: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
