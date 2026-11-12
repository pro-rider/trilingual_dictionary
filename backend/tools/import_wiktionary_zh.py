"""Import safe Chinese Wiktionary definitions into `senses.gloss_zh`.

Source: zh.wiktionary, CC BY-SA 4.0 (redistributable with attribution). Every
imported sense records source, license and method in `gloss_provenance`, so the
release audit can prove what came from where.

Gates — a candidate is imported only if ALL of these hold:
  * its title equals the entry's simplified or traditional form exactly;
  * the entry has exactly one sense (one definition cannot serve several
    senses without guessing which one it means);
  * that sense's `gloss_zh` is still empty (never overwrite existing text);
  * the definition is 4..120 characters after normalisation;
  * it carries no wiki syntax (`{{`, `[[`, `ref=`), no stub pointer
    ("见…", "参见…", "另见…", "同…") and no markup residue;
  * the entry is outside the auto-import exclusion window: an entry with
    `freq_rank <= --auto-max-rank` (default 10,000) is routed to review
    instead, because for the highest-frequency words Wiktionary usually lists
    classical meanings first (`的` → "白色；箭靶中心").
  * the entry is not in launch tiers 1-2, which are reviewed row by row.

Everything else stays a candidate. Text is converted Traditional → Simplified
with OpenCC and the conversion is recorded.

    python tools/import_wiktionary_zh.py --dry-run
    python tools/import_wiktionary_zh.py
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB = REPO_ROOT / "backend" / "data" / "build" / "dictionary.sqlite"
SOURCE = "zh.wiktionary"
LICENSE = "CC BY-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
MIN_CHARS = 4
MAX_CHARS = 120
STUB_PREFIXES = ("见", "参见", "另见", "同", "參見", "另參", "參")
JUNK_MARKERS = ("{{", "}}", "[[", "]]", "ref=", "<", ">", "|")

DDL = """
CREATE TABLE IF NOT EXISTS gloss_provenance (
  sense_id    INTEGER PRIMARY KEY,
  entry_id    INTEGER NOT NULL,
  source      TEXT NOT NULL,
  license     TEXT NOT NULL,
  license_url TEXT,
  method      TEXT NOT NULL,
  confidence  TEXT NOT NULL,
  run_id      TEXT NOT NULL,
  applied_at  TEXT NOT NULL
)
"""


def _converter():
    try:
        from opencc import OpenCC

        return OpenCC("t2s").convert
    except Exception:  # pragma: no cover - reported, not hidden
        return None


def normalise(text: str, convert) -> str:
    text = " ".join((text or "").split())
    if convert:
        text = convert(text)
    return text.strip("；;。 ")


def grade(text: str, exact_simplified: bool) -> str | None:
    """Return a confidence label, or None when the row must not be imported."""
    if not text or not (MIN_CHARS <= len(text) <= MAX_CHARS):
        return None
    if any(marker in text for marker in JUNK_MARKERS):
        return None
    if text.startswith(STUB_PREFIXES):
        return None
    if not any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return None  # no Chinese characters: not a Chinese definition
    return "high" if exact_simplified and len(text) >= 6 else "medium"


def collect(con: sqlite3.Connection, convert, auto_max_rank: int, run_id: str):
    rows = con.execute(
        """
        SELECT c.entry_id, c.title, c.definition_zh, c.def_chars,
               e.simplified, e.traditional, e.freq_rank,
               l.tier,
               (SELECT count(*) FROM senses s WHERE s.entry_id = c.entry_id) AS sense_count,
               (SELECT s.sense_id FROM senses s WHERE s.entry_id = c.entry_id
                 AND s.sense_order = 0) AS sense_id,
               (SELECT s.gloss_zh FROM senses s WHERE s.entry_id = c.entry_id
                 AND s.sense_order = 0) AS current_gloss
        FROM gloss_zh_wikt_candidates c
        JOIN entries e ON e.entry_id = c.entry_id
        LEFT JOIN launch_set l ON l.entry_id = c.entry_id
        """
    ).fetchall()

    accepted, reasons = [], {}
    for entry_id, title, definition, _chars, simp, trad, rank, tier, n_senses, \
            sense_id, current in rows:
        def reject(reason):
            reasons[reason] = reasons.get(reason, 0) + 1

        title = (title or "").strip()
        if n_senses != 1:
            reject("multi_sense_entry")
            continue
        if current:
            reject("gloss_zh_already_present")
            continue
        if sense_id is None:
            reject("no_sense_order_0")
            continue
        if rank is not None and rank <= auto_max_rank:
            reject("high_frequency_review_only")
            continue
        if tier is not None and tier <= 2:
            reject("launch_set_review_only")
            continue
        exact_simplified = title == (simp or "").strip()
        if not (exact_simplified or title == (trad or "").strip()):
            reject("title_mismatch")
            continue
        text = normalise(definition, convert)
        confidence = grade(text, exact_simplified)
        if confidence is None:
            reject("definition_quality")
            continue
        accepted.append({
            "sense_id": sense_id, "entry_id": entry_id, "gloss": text,
            "confidence": confidence,
            "method": "zh.wiktionary definition_zh, t2s" if convert
            else "zh.wiktionary definition_zh, raw",
            "run_id": run_id,
        })
    return accepted, reasons


def coverage(con: sqlite3.Connection) -> dict:
    total = con.execute("SELECT count(*) FROM senses").fetchone()[0]
    filled = con.execute(
        "SELECT count(*) FROM senses WHERE gloss_zh IS NOT NULL AND trim(gloss_zh)!=''"
    ).fetchone()[0]
    launch_total = con.execute(
        "SELECT count(*) FROM senses WHERE entry_id IN "
        "(SELECT entry_id FROM launch_set WHERE tier<=2)"
    ).fetchone()[0]
    launch_filled = con.execute(
        "SELECT count(*) FROM senses WHERE gloss_zh IS NOT NULL AND trim(gloss_zh)!='' "
        "AND entry_id IN (SELECT entry_id FROM launch_set WHERE tier<=2)"
    ).fetchone()[0]
    return {
        "senses_total": total,
        "senses_with_zh": filled,
        "zh_coverage_pct": round(100 * filled / total, 2) if total else 0,
        "launch_senses_total": launch_total,
        "launch_senses_with_zh": launch_filled,
        "launch_zh_coverage_pct": round(100 * launch_filled / launch_total, 2)
        if launch_total else 0,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--auto-max-rank", type=int, default=10000,
                    help="entries at or above this frequency go to review only")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args(argv)

    run_id = args.run_id or datetime.now(timezone.utc).strftime("wikt-%Y%m%dT%H%M%SZ")
    con = sqlite3.connect(args.db)
    con.executescript(DDL)
    convert = _converter()
    if convert is None:
        print("WARNING: opencc unavailable, importing traditional text as-is")

    before = coverage(con)
    accepted, reasons = collect(con, convert, args.auto_max_rank, run_id)
    print(f"candidates accepted: {len(accepted)}")
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  rejected {reason}: {count}")

    if args.dry_run:
        for row in accepted[:5]:
            print(f"  {row['entry_id']} {row['confidence']}: {row['gloss'][:40]}")
        print("dry run: nothing written")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    con.executemany(
        "UPDATE senses SET gloss_zh=? WHERE sense_id=? AND "
        "(gloss_zh IS NULL OR trim(gloss_zh)='')",
        [(row["gloss"], row["sense_id"]) for row in accepted],
    )
    con.executemany(
        "INSERT OR REPLACE INTO gloss_provenance "
        "(sense_id, entry_id, source, license, license_url, method, confidence, "
        " run_id, applied_at) VALUES (?,?,?,?,?,?,?,?,?)",
        [(row["sense_id"], row["entry_id"], SOURCE, LICENSE, LICENSE_URL,
          row["method"], row["confidence"], row["run_id"], now)
         for row in accepted],
    )
    con.commit()
    after = coverage(con)
    print("before:", before)
    print("after :", after)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
