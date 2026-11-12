"""Inventory + integrity check of review/*.xlsx (Release Gatekeeper, Part A).

For every workbook: does it open, does it have the Review sheet, are the 10
headers exactly the documented contract, how many data rows, size, sha256 and
mtime. Compares rows against the table in review/README.md so a mismatch is
reported instead of assumed away.
"""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

REVIEW = Path(r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\review")
EXPECTED_HEADERS = ["entry_id", "headword", "pinyin", "English gloss",
                    "Nepali (machine)", "Chinese candidate", "source",
                    "decision", "edited_text", "reviewer_notes"]
TOPICS = {"nepali-launch": 6, "chinese-highfreq": 11, "new-words": 3, "examples": 1}


def readme_table() -> dict[str, int]:
    text = (REVIEW / "README.md").read_text(encoding="utf-8")
    rows = {}
    for match in re.finditer(r"\| `([^`]+\.xlsx)` \| (\d+) \|", text):
        rows[match.group(1)] = int(match.group(2))
    return rows


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    declared = readme_table()
    files = sorted(REVIEW.glob("*.xlsx"))
    problems: list[str] = []
    total_bytes = 0

    print(f"readme declares {len(declared)} workbooks; disk has {len(files)}")
    if len(files) != sum(TOPICS.values()):
        problems.append(f"expected {sum(TOPICS.values())} workbooks, found {len(files)}")

    for path in files:
        size = path.stat().st_size
        total_bytes += size
        mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        try:
            wb = load_workbook(path, read_only=True)
        except Exception as exc:  # noqa: BLE001 - report every unreadable file
            problems.append(f"{path.name}: cannot open ({exc})")
            print(f"FAIL  {path.name:32} unreadable: {exc}")
            continue
        sheets = wb.sheetnames
        if "Review" not in sheets:
            problems.append(f"{path.name}: no Review sheet (has {sheets})")
        ws = wb["Review"]
        header = [c for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
        header = [h for h in header if h is not None]
        if header[:10] != EXPECTED_HEADERS:
            problems.append(f"{path.name}: header differs -> {header[:10]}")
        data_rows = max(ws.max_row - 1, 0)
        if path.name in declared and declared[path.name] != data_rows:
            problems.append(
                f"{path.name}: README says {declared[path.name]} rows, file has {data_rows}")
        if path.name not in declared:
            problems.append(f"{path.name}: not listed in README")
        wb.close()
        print(f"ok    {path.name:32} {data_rows:>4} rows  {size:>8,} B  "
              f"{mtime}  sha256={sha256(path)[:16]}")

    # every topic's part numbering must be contiguous
    for topic, expected in TOPICS.items():
        parts = sorted(p for p in files if p.name.startswith(topic + "-part-"))
        if len(parts) != expected:
            problems.append(f"{topic}: {len(parts)} parts, expected {expected}")

    print(f"\ntotal {len(files)} workbooks, {total_bytes:,} bytes "
          f"({total_bytes / 1048576:.2f} MB)")
    if problems:
        print("\nPROBLEMS")
        for problem in problems:
            print("  -", problem)
        return 1
    print("ALL WORKBOOKS VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
