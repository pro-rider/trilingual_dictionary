#!/usr/bin/env python
"""Print the current state of the dictionary database.

Read-only. Safe to run against the working database or a release build.

Usage:
    python tools/metrics.py                # print to stdout
    python tools/metrics.py --out docs/metrics_before.txt
    python tools/metrics.py --db <path> --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "backend" / "data" / "build" / "dictionary.sqlite"
PACKAGED = REPO_ROOT / "assets" / "data" / "dictionary.sqlite.gz"


def _open_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"database not found: {path}")
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _scalar(con: sqlite3.Connection, sql: str, default=0):
    try:
        row = con.execute(sql).fetchone()
    except sqlite3.Error:
        return default
    return row[0] if row else default


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return _scalar(
        con,
        f"select count(*) from sqlite_master where type in ('table','view') and name='{name}'",
    ) > 0


def collect(db_path: Path) -> dict:
    con = _open_ro(db_path)
    entries = _scalar(con, "select count(*) from entries")
    senses = _scalar(con, "select count(*) from senses")

    zh_gap = _scalar(
        con,
        "select count(*) from senses where gloss_zh is null or trim(gloss_zh) = ''",
    )
    ne_filled = _scalar(
        con,
        "select count(*) from senses where gloss_ne is not null and trim(gloss_ne) <> ''",
    )
    ne_reviewed = _scalar(
        con, "select count(*) from senses where ne_status = 'reviewed'"
    )
    ne_ai = _scalar(
        con, "select count(*) from senses where ne_status = 'ai_translated'"
    )
    en_gap = _scalar(
        con,
        "select count(*) from senses where gloss_en is null or trim(gloss_en) = ''",
    )

    examples = _scalar(con, "select count(*) from examples")
    example_status = {}
    try:
        for status, n in con.execute(
            "select review_status, count(*) from examples group by review_status"
        ):
            example_status[status] = n
    except sqlite3.Error:
        pass

    classifiers = _scalar(con, "select count(*) from entry_classifiers")
    classifier_distinct = _scalar(
        con, "select count(distinct classifier) from entry_classifiers"
    )
    hsk = _scalar(con, "select count(*) from entries where hsk_level is not null")

    images_total = _scalar(con, "select count(*) from images")
    images_approved = _scalar(con, "select count(*) from images where status='approved'")
    image_asset_states = {}
    try:
        for state, n in con.execute(
            "select asset_status, count(*) from images group by asset_status"
        ):
            image_asset_states[state] = n
    except sqlite3.Error:
        pass

    meta = {}
    try:
        for key, value in con.execute("select key, value from meta"):
            meta[key] = value
    except sqlite3.Error:
        pass

    candidates = {}
    for name in (
        "words3000_candidates",
        "gloss_zh_candidates",
        "gloss_zh_wikt_candidates",
        "launch_set",
        "gloss_provenance",
        "review_audit",
    ):
        if _table_exists(con, name):
            candidates[name] = _scalar(con, f"select count(*) from '{name}'")
    con.close()

    def pct(part: int, whole: int) -> float:
        return round(100.0 * part / whole, 2) if whole else 0.0

    payload = {
        "db_path": str(db_path),
        "db_size_bytes": db_path.stat().st_size,
        "packaged_path": str(PACKAGED),
        "packaged_size_bytes": PACKAGED.stat().st_size if PACKAGED.exists() else 0,
        "entries": entries,
        "senses": senses,
        "gloss_en_gap": en_gap,
        "gloss_zh_gap": zh_gap,
        "gloss_zh_gap_pct": pct(zh_gap, senses),
        "gloss_zh_coverage_pct": round(100 - pct(zh_gap, senses), 2),
        "gloss_ne_filled": ne_filled,
        "gloss_ne_coverage_pct": pct(ne_filled, senses),
        "ne_status": {"ai_translated": ne_ai, "reviewed": ne_reviewed},
        "examples": examples,
        "example_status": example_status,
        "classifier_rows": classifiers,
        "classifier_distinct": classifier_distinct,
        "hsk_tagged": hsk,
        "images": {
            "total": images_total,
            "approved": images_approved,
            "asset_status": image_asset_states,
        },
        "meta": meta,
        "candidate_tables": candidates,
    }
    if _table_exists(con, "entries"):
        pass
    return payload


def render(payload: dict) -> str:
    lines = []
    lines.append(f"database   : {payload['db_path']}")
    lines.append(
        f"db size    : {payload['db_size_bytes']:,} bytes "
        f"({payload['db_size_bytes'] / 1048576:.1f} MiB)"
    )
    lines.append(
        f"packaged   : {payload['packaged_size_bytes']:,} bytes "
        f"({payload['packaged_size_bytes'] / 1048576:.1f} MiB)"
    )
    lines.append(f"entries    : {payload['entries']:,}")
    lines.append(f"senses     : {payload['senses']:,}")
    lines.append(f"gloss_en gap: {payload['gloss_en_gap']:,}")
    lines.append(
        f"gloss_zh gap: {payload['gloss_zh_gap']:,} "
        f"({payload['gloss_zh_gap_pct']}% empty, "
        f"coverage {payload['gloss_zh_coverage_pct']}%)"
    )
    lines.append(
        f"gloss_ne    : {payload['gloss_ne_filled']:,} filled "
        f"({payload['gloss_ne_coverage_pct']}%); status {payload['ne_status']}"
    )
    lines.append(f"examples   : {payload['examples']:,} {payload['example_status']}")
    lines.append(
        f"classifiers: {payload['classifier_rows']:,} rows / "
        f"{payload['classifier_distinct']} distinct"
    )
    lines.append(f"hsk tagged : {payload['hsk_tagged']:,}")
    lines.append(
        f"images     : {payload['images']['total']} total, "
        f"{payload['images']['approved']} approved, {payload['images']['asset_status']}"
    )
    lines.append("meta       : " + ", ".join(f"{k}={v}" for k, v in payload["meta"].items()))
    lines.append("candidates : " + (json.dumps(payload["candidate_tables"]) or "{}"))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", default=None, help="write the text report to this file")
    args = parser.parse_args()

    payload = collect(Path(args.db))
    text = json.dumps(payload, indent=2, ensure_ascii=False) if args.json else render(payload)
    print(text)
    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
