"""Fill the gaps CC-CEDICT leaves behind: Nepali glosses and example sentences.

CC-CEDICT gives Chinese + English only, so 195k of 198k senses had no Nepali
gloss and every entry had zero example sentences — the app's नेपाली box was
empty and learners got a definition with nothing to read it in. This tool asks
the LLM for both in one call per batch and writes them back into the same
SQLite file, so the packaged dictionary (project_guide §8.7) carries them.

Resumable by construction: it only selects senses that still need work, so
Ctrl-C and rerun is safe.

Usage:
    python tools/enrich_dictionary.py --db data/build/dictionary.sqlite --dry-run
    python tools/enrich_dictionary.py --db data/build/dictionary.sqlite --limit 100
    python tools/enrich_dictionary.py --db data/build/dictionary.sqlite --primary-only

    --primary-only   only sense_order = 0 (38% less work; the app shows the
                     first sense by default, so this is the cheap first pass)
    --batch N        senses per LLM call (default 25; 30+ degrades JSON quality)
    --threads N      parallel calls (default 6)
    --report PATH    JSON report (default: <db>.enrich.report.json)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.provider import ai_enabled, enrich_senses_batch  # noqa: E402

PRIMARY_SQL = """
SELECT s.sense_id, s.sense_order, s.gloss_en, e.simplified, e.entry_id
FROM senses s JOIN entries e ON e.entry_id = s.entry_id
WHERE ((s.gloss_ne IS NULL OR s.gloss_ne = '')
   OR NOT EXISTS (SELECT 1 FROM examples x WHERE x.sense_id = s.sense_id))
"""


def pending_rows(con: sqlite3.Connection, primary_only: bool, limit: int | None,
                 hsk_only: bool = False) -> list[tuple]:
    sql = PRIMARY_SQL
    if primary_only:
        sql += " AND s.sense_order = 0"
    if hsk_only:
        sql += " AND e.hsk_level = 5"
    sql += " ORDER BY s.sense_id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return con.execute(sql).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--primary-only", action="store_true")
    ap.add_argument("--hsk-only", action="store_true",
                    help="restrict to the 2,477 HSK5-tagged entries (the words the "
                         "student actually studies); ~1.7 h on free-tier keys")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"missing database: {db}")
        return 2
    if not args.dry_run and not ai_enabled():
        print("AI is not configured (no provider keys) — nothing to do.")
        return 2

    con = sqlite3.connect(db, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")

    rows = pending_rows(con, args.primary_only, args.limit, args.hsk_only)
    total = len(rows)
    print(f"pending senses: {total:,} (primary_only={args.primary_only}, "
          f"hsk_only={args.hsk_only})")
    if args.dry_run:
        sample = rows[:8]
        for r in sample:
            print(f"  {r[4]:>6}  {r[3]}  [{r[2][:40]}]")
        print(f"estimated calls: {max(1, -(-total // args.batch)):,} "
              f"at batch={args.batch} threads={args.threads}")
        return 0
    if not rows:
        print("nothing to do — the dictionary is already complete.")
        return 0

    batches: list[list[tuple]] = [rows[i:i + args.batch] for i in range(0, total, args.batch)]
    lock = threading.Lock()
    done = {"senses": 0, "ne": 0, "examples": 0, "failed_batches": 0}
    started = time.time()
    report_path = Path(args.report or str(db) + ".enrich.report.json")
    last_report = time.time()

    def write_back(payload: dict[str, dict[str, str]], keys: dict[str, tuple]) -> None:
        ne_n = ex_n = 0
        with lock:
            for key, meta in keys.items():
                item = payload.get(key)
                if not item:
                    continue
                sense_id = meta[0]
                ne = item.get("ne") or ""
                if ne:
                    cur = con.execute(
                        "UPDATE senses SET gloss_ne = ?, ne_status = 'ai_translated' "
                        "WHERE sense_id = ? AND (gloss_ne IS NULL OR gloss_ne = '')",
                        (ne, sense_id),
                    )
                    ne_n += cur.rowcount
                example_en = item.get("example_en") or ""
                if example_en:
                    exists = con.execute(
                        "SELECT 1 FROM examples WHERE sense_id = ?", (sense_id,)
                    ).fetchone()
                    if not exists:
                        con.execute(
                            "INSERT INTO examples (sense_id, en, zh, ne) VALUES (?,?,?,?)",
                            (sense_id, example_en, item.get("example_zh") or "",
                             item.get("example_ne") or ""),
                        )
                        ex_n += 1
            con.commit()
            done["senses"] += len(keys)
            done["ne"] += ne_n
            done["examples"] += ex_n

    for bi, batch in enumerate(batches, 1):
        keys = {f"s{row[0]}": (row[0], row[3], row[2]) for row in batch}
        payload = enrich_senses_batch([(k, zh, en) for k, (_, zh, en) in keys.items()])
        if not payload:
            done["failed_batches"] += 1
        else:
            write_back(payload, keys)

        elapsed = time.time() - started
        rate = done["senses"] / elapsed if elapsed else 0
        eta = (total - done["senses"]) / rate / 60 if rate else 0
        if bi % 10 == 0 or bi == len(batches):
            print(f"[{bi}/{len(batches)}] senses={done['senses']:,}/{total:,} "
                  f"ne={done['ne']:,} examples={done['examples']:,} "
                  f"{rate:.1f}/s eta={eta:.0f}min fail_batches={done['failed_batches']}",
                  flush=True)
        if time.time() - last_report > 60:
            report_path.write_text(json.dumps({
                "total": total, "done": done["senses"], "ne": done["ne"],
                "examples": done["examples"], "rate_per_s": round(rate, 2),
                "eta_min": round(eta, 1), "failed_batches": done["failed_batches"],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            last_report = time.time()

    con.commit()
    report = {
        "total": total,
        "done": done["senses"],
        "ne": done["ne"],
        "examples": done["examples"],
        "elapsed_s": round(time.time() - started, 1),
        "failed_batches": done["failed_batches"],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
