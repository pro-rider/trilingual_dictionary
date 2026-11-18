"""Split/merge helpers for running image enrichment in parallel shards.

One sequential run of ``enrich_csv_images.py`` over 123k rows is latency bound:
each row waits on a network round-trip, so the wall clock is roughly rows x
latency regardless of how fast the disk is. Splitting the input into independent
shards lets several polite crawlers run side by side, then this script stitches
the results back into one file in the original row order.

Usage:
    python tools/merge_image_shards.py split data/build/image_gap_queries.csv 8 .cache/shards
    python tools/merge_image_shards.py merge .cache/shards data/build/image_links/image_gap_images.csv

Split writes ``shard_00.csv`` ... ``shard_07.csv`` with the original header on
each shard. Merge accepts the shard input files or their ``*_out.csv`` results,
keeps the header of the first file, and orders rows by ``entry_id`` when that
column exists so the merged output lines up with the source list.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def split(source: Path, parts: int, out_dir: Path) -> list[Path]:
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ValueError(f"{source} is empty")
    header, body = rows[0], rows[1:]
    out_dir.mkdir(parents=True, exist_ok=True)
    per = -(-len(body) // parts)
    written: list[Path] = []
    for index in range(parts):
        chunk = body[index * per:(index + 1) * per]
        if not chunk:
            continue
        path = out_dir / f"shard_{index:02d}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(chunk)
        written.append(path)
    print(f"split {len(body)} rows into {len(written)} shards of ~{per} rows in {out_dir}")
    return written


def merge(shard_dir: Path, destination: Path) -> None:
    files = sorted(p for p in shard_dir.glob("*_out.csv"))
    if not files:
        files = sorted(p for p in shard_dir.glob("shard_*.csv"))
    if not files:
        raise SystemExit(f"no shard outputs found in {shard_dir}")
    header: list[str] | None = None
    rows: list[list[str]] = []
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            shard_header = next(reader, None)
            if shard_header is None:
                continue
            if header is None:
                header = shard_header
            elif shard_header != header:
                raise SystemExit(f"header mismatch in {path.name}: {shard_header} != {header}")
            rows.extend(row for row in reader if row)
    if "entry_id" in (header or []):
        index = header.index("entry_id")
        try:
            rows.sort(key=lambda row: int(row[index]))
        except (ValueError, IndexError):
            pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    filled = 0
    if "image_link" in (header or []):
        link_index = header.index("image_link")
        filled = sum(1 for row in rows if len(row) > link_index and row[link_index])
    print(f"merged {len(files)} files -> {destination} ({len(rows)} rows, {filled} with image_link)")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    command = argv[1]
    if command == "split" and len(argv) == 5:
        split(Path(argv[2]), int(argv[3]), Path(argv[4]))
        return 0
    if command == "merge" and len(argv) == 4:
        merge(Path(argv[2]), Path(argv[3]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
