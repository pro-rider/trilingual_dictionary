"""Build the launch set: which entries we are actually launching with.

Tier 1  every entry carrying an HSK level (the vocabulary a learner is told to
        study first).
Tier 2  the next most frequent entries up to `--tier2-total` entries in tiers 1+2.
Tier 3  everything else, explicit so later phases can report "x of y" without
        re-deriving the boundary.

The table is planning data: the release build drops it (see
`docs/ASSUMPTIONS.md` A1). Reproducible: re-running with the same arguments
produces the same rows, and the script prints a digest so drift is visible.

    python tools/build_launch_set.py                 # build / refresh
    python tools/build_launch_set.py --report-only    # print without touching the DB
    python tools/build_launch_set.py --drop
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB = REPO_ROOT / "backend" / "data" / "build" / "dictionary.sqlite"
TIER2_TOTAL_DEFAULT = 5000

DDL = """
CREATE TABLE IF NOT EXISTS launch_set (
  entry_id INTEGER PRIMARY KEY,
  tier     INTEGER NOT NULL,
  reason   TEXT NOT NULL
)
"""


def build(con: sqlite3.Connection, tier2_total: int) -> dict:
    con.executescript(DDL)
    con.execute("DELETE FROM launch_set")

    rows = []
    hsk = con.execute(
        "SELECT entry_id, hsk_level FROM entries WHERE hsk_level IS NOT NULL "
        "ORDER BY hsk_level, entry_id"
    ).fetchall()
    for entry_id, level in hsk:
        rows.append((entry_id, 1, f"hsk_level={level}"))

    tier1 = {r[0] for r in rows}
    budget = max(tier2_total - len(tier1), 0)
    if budget:
        candidates = con.execute(
            "SELECT entry_id, freq_rank FROM entries WHERE freq_rank IS NOT NULL "
            "ORDER BY freq_rank, entry_id"
        ).fetchall()
        added = 0
        for entry_id, rank in candidates:
            if entry_id in tier1:
                continue
            rows.append((entry_id, 2, f"freq_rank={rank}"))
            added += 1
            if added >= budget:
                break

    covered = {r[0] for r in rows}
    for entry_id, in con.execute("SELECT entry_id FROM entries ORDER BY entry_id"):
        if entry_id not in covered:
            rows.append((entry_id, 3, "post_launch"))

    con.executemany("INSERT INTO launch_set VALUES (?,?,?)", rows)
    con.commit()
    return report(con)


def report(con: sqlite3.Connection) -> dict:
    counts = dict(
        con.execute("SELECT tier, count(*) FROM launch_set GROUP BY tier")
        .fetchall()
    )
    total = sum(counts.values())
    # The launch set proper is tiers 1+2; tier 3 is "everything else, after launch"
    # and must never inflate the coverage share.
    senses = con.execute(
        "SELECT count(*) FROM senses WHERE entry_id IN "
        "(SELECT entry_id FROM launch_set WHERE tier <= 2)"
    ).fetchone()[0]
    all_senses = con.execute("SELECT count(*) FROM senses").fetchone()[0]
    # Overlap: an entry can only hold one tier, so a non-zero overlap would mean
    # the builder wrote the same entry twice. It is reported, not assumed away.
    dupes = con.execute(
        "SELECT count(*) FROM (SELECT entry_id FROM launch_set GROUP BY entry_id "
        "HAVING count(*) > 1)"
    ).fetchone()[0]
    digest = hashlib.sha256(
        "\n".join(
            f"{eid}:{tier}"
            for eid, tier in con.execute(
                "SELECT entry_id, tier FROM launch_set ORDER BY entry_id"
            )
        ).encode("utf-8")
    ).hexdigest()
    return {
        "tier1_hsk": counts.get(1, 0),
        "tier2_frequency": counts.get(2, 0),
        "tier3_post_launch": counts.get(3, 0),
        "total": total,
        "entries_in_db": con.execute("SELECT count(*) FROM entries").fetchone()[0],
        "senses_in_launch_set": senses,
        "senses_in_db": all_senses,
        "senses_share_pct": round(100 * senses / all_senses, 2) if all_senses else 0,
        "duplicate_entry_ids": dupes,
        "digest": digest,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--tier2-total", type=int, default=TIER2_TOTAL_DEFAULT,
                    help="size of tier 1 + tier 2 combined")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--drop", action="store_true")
    ap.add_argument("--out", default=str(REPO_ROOT / "docs" / "launch_set.txt"))
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    if args.drop:
        con.execute("DROP TABLE IF EXISTS launch_set")
        con.commit()
        print("launch_set dropped")
        return 0

    data = report(con) if args.report_only else build(con, args.tier2_total)
    lines = [f"{k}: {v}" for k, v in data.items()]
    text = "\n".join(lines)
    print(text)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
