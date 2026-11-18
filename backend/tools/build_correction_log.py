"""Emit one audit log of every gloss cell that was filled or rewritten.

The repair step fills cells in the *exported CSVs* while the audit's ``--apply``
rewrites cells in the *database*; both write their own files. For review it is
useful to have a single list of "what changed, where, from what to what", with
the original and replacement side by side.

Usage:
    python tools/build_correction_log.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

BASE = Path(
    r"C:\Users\Administrator\AppData\Local\Packages\5319275A.WhatsAppDesktop_cv1g1gvanyjgm"
    r"\LocalState\sessions\BFC289ED38E0768C37BD4CCABB075ECBC877F5EB\transfers\2026-47"
)
FILES = ("vocabulary_table_clean.csv", "vocabulary_table2_clean.csv")
COLUMNS = ("gloss_en", "gloss_zh", "gloss_ne")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    out_dir = Path("data/build/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []

    for name in FILES:
        original = read_rows(BASE / name)
        repaired = read_rows(Path("data/build/repaired") / f"{Path(name).stem}_repaired.csv")
        for before, after in zip(original, repaired):
            word = (before.get("word") or "").strip()
            for column in COLUMNS:
                if column not in before:
                    continue
                old = (before.get(column) or "").strip()
                new = (after.get(column) or "").strip()
                if old != new:
                    entries.append({
                        "source": name,
                        "word": word,
                        "column": column,
                        "old_value": old,
                        "new_value": new,
                        "action": "filled_from_database",
                    })

    db_log = Path("data/build/reports/meaning_autofix_log.csv")
    if db_log.exists():
        for row in read_rows(db_log):
            entries.append({
                "source": "dictionary.sqlite",
                "word": row.get("word", ""),
                "column": row.get("column", ""),
                "old_value": row.get("old_value", ""),
                "new_value": row.get("new_value", ""),
                "action": f"database_{row.get('issue', 'fix')}",
            })

    path = out_dir / "gloss_corrections_log.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source", "word", "column", "old_value", "new_value", "action"])
        writer.writeheader()
        writer.writerows(entries)
    print(f"corrections logged: {len(entries)} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
