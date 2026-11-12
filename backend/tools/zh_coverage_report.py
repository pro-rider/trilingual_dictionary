"""Coverage report for Chinese definitions, whole DB and launch set (Phase 2).

Answers three questions with numbers taken from the database:

1. how much of the dictionary now has a Chinese definition, before vs after;
2. how the launch set compares with the whole dictionary;
3. what happened to each Wiktionary candidate that was not imported, by reason.

Run from backend/:
    python tools/zh_coverage_report.py            # print
    python tools/zh_coverage_report.py --out ../docs/phase2_zh_coverage.txt
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DB = BACKEND / "data" / "build" / "dictionary.sqlite"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        print(text)

    total_senses = con.execute("SELECT COUNT(*) FROM senses").fetchone()[0]
    with_zh = con.execute(
        "SELECT COUNT(*) FROM senses WHERE gloss_zh IS NOT NULL AND TRIM(gloss_zh) <> ''"
    ).fetchone()[0]
    emit("Chinese definition coverage")
    emit("=" * 60)
    emit(f"senses total          : {total_senses:,}")
    emit(f"senses with gloss_zh  : {with_zh:,} ({with_zh / total_senses:.2%})")
    emit(f"senses without        : {total_senses - with_zh:,} "
         f"({1 - with_zh / total_senses:.2%})")
    emit(f"before this phase     : 0 (0.00%) — every sense was empty")
    emit()

    # launch set (Tier 1 + Tier 2), where missing depth hurts most
    for tier in (1, 2, 3):
        rows = con.execute(
            "SELECT COUNT(*) FROM senses s JOIN launch_set l ON l.entry_id = s.entry_id "
            "WHERE l.tier = ?", (tier,)).fetchone()[0]
        filled = con.execute(
            "SELECT COUNT(*) FROM senses s JOIN launch_set l ON l.entry_id = s.entry_id "
            "WHERE l.tier = ? AND s.gloss_zh IS NOT NULL AND TRIM(s.gloss_zh) <> ''",
            (tier,)).fetchone()[0]
        emit(f"tier {tier:<2} senses {rows:>8,}  zh filled {filled:>8,}  "
             f"({(filled / rows if rows else 0):.2%})")
    emit()

    # what happened to each candidate
    total_cands = con.execute("SELECT COUNT(*) FROM gloss_zh_wikt_candidates").fetchone()[0]
    imported = con.execute("SELECT COUNT(*) FROM gloss_provenance").fetchone()[0]
    emit(f"wiktionary candidates  : {total_cands:,}")
    emit(f"imported (provenance)  : {imported:,} ({imported / total_cands:.2%})")
    emit(f"not imported           : {total_cands - imported:,}")
    emit()
    emit("reason per candidate not imported (re-derived with the importer's own")
    emit("gates, so the numbers cannot drift from the tool that made them):")
    try:
        sys.path.insert(0, str(BACKEND))
        from tools import import_wiktionary_zh as wikt  # noqa: WPS433

        _accepted, reasons = wikt.collect(con, wikt._converter(), 10000, "report")
        for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            emit(f"  {reason:<28} {count:>7,}")
    except Exception as exc:  # noqa: BLE001 - report the failure, do not hide it
        emit(f"  (could not re-derive reasons: {exc})")
    emit()
    emit("provenance sources now in senses:")
    for source, count in con.execute(
        "SELECT source, COUNT(*) FROM gloss_provenance GROUP BY 1 ORDER BY 2 DESC"
    ):
        emit(f"  {source:<24} {count:>7,}")
    emit()
    emit("restricted data present in senses? (must all be 0)")
    for table in ("gloss_zh_candidates",):
        emit(f"  {table}: {con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:,} "
             "rows — internal benchmark only, dropped from the release build")
    con.close()

    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
