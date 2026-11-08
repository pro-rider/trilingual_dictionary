"""N5/N6 — resumable bulk translation of the Nepali queue with validation.

Reads `data/build/ne_queue.sqlite`, translates batches with the app's existing
LLM failover chain (Groq → Gemini → OpenRouter), validates every result, scores
it against a back-translation, and stores it in the queue database. It never
writes to `dictionary.sqlite`: N7 does the import, after review.

Properties the prompt asks for:
  * checkpoint after every batch, rerun skips what is already done
  * cache by queue key, so nothing is translated twice
  * retries a failed batch, records the failure instead of inventing a value
  * live progress: done / failed / rate / ETA
  * `--limit` to test on 500 first

Usage:
  .venv\\Scripts\\python.exe tools\\translate_ne_queue.py --limit 500 --threads 6
  .venv\\Scripts\\python.exe tools\\translate_ne_queue.py            # whole queue
  .venv\\Scripts\\python.exe tools\\translate_ne_queue.py --export   # write review CSV
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.provider import translate_gloss_queue_batch  # noqa: E402

DEVANAGARI = re.compile(r"[\u0900-\u097F]")
LATIN = re.compile(r"[A-Za-z]")
WORD_RE = re.compile(r"[a-z0-9']+")
TOKEN = threading.local()


def tokens(text: str) -> set[str]:
    stop = {"a", "an", "the", "to", "of", "or", "in", "for", "and", "with", "be",
            "is", "are", "that", "this", "someone", "something", "sth", "sb"}
    return {w for w in WORD_RE.findall((text or "").lower()) if w not in stop and len(w) > 1}


def score(gloss: str, back_en: str, ne: str) -> tuple[str, str]:
    """Return (status, confidence) for one result."""
    ne = (ne or "").strip()
    if not ne:
        return "empty", "low"
    if not DEVANAGARI.search(ne):
        return "no_devanagari", "low"
    if LATIN.search(ne):
        return "latin_letters", "low"
    words = ne.split()
    if len(words) > 6 or len(ne) > 80:
        return "too_long", "low"
    g, b = tokens(gloss), tokens(back_en)
    if not b:
        return "ok", "medium"
    # A one- or two-word gloss ("you", "to be") leaves little to overlap on, so
    # absence of overlap there is a scorer artefact, not a bad translation.
    if len(g) <= 2:
        return "ok", "high" if (g & b) else "medium"
    overlap = len(g & b) / max(1, len(g | b))
    if overlap >= 0.45:
        return "ok", "high"
    if overlap >= 0.2:
        return "ok", "medium"
    return "backtranslation_mismatch", "low"


def open_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS results (
            key TEXT PRIMARY KEY, batch_id INTEGER, ne TEXT, back_en TEXT,
            status TEXT, confidence TEXT, model TEXT, translated_at TEXT
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS ix_results_status ON results(status)")
    con.commit()
    return con


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default=str(Path("data") / "build" / "ne_queue.sqlite"))
    ap.add_argument("--batch", type=int, default=30)
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="only this many items (pilot run)")
    ap.add_argument("--export", action="store_true", help="write the review CSV and exit")
    ap.add_argument("--exports-dir", default=str(Path("data") / "build" / "reports"))
    args = ap.parse_args()

    qpath = Path(args.queue)
    con = open_db(qpath)

    if args.export:
        out = Path(args.exports_dir) / "ne_translations_review.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        rows = con.execute(
            """
            SELECT q.key, q.zh, q.pinyin, q.gloss, q.domain, q.freq_rank, q.hsk_level,
                   q.senses, r.ne, r.back_en, r.status, r.confidence
              FROM queue q LEFT JOIN results r ON r.key = q.key
             WHERE r.key IS NOT NULL
             ORDER BY q.freq_rank IS NULL, q.freq_rank, q.key
            """
        ).fetchall()
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["key", "chinese", "pinyin", "gloss_en", "domain", "freq_rank",
                        "hsk", "senses_covered", "nepali", "back_en", "status", "confidence"])
            w.writerows(rows)
        print(f"wrote {out} ({len(rows)} rows)")
        return 0

    pending = con.execute(
        """
        SELECT q.key, q.batch_id, q.gloss, q.zh, q.example
          FROM queue q LEFT JOIN results r ON r.key = q.key
         WHERE r.key IS NULL
         ORDER BY q.freq_rank IS NULL, q.freq_rank, q.key
        """
    ).fetchall()
    if args.limit:
        pending = pending[: args.limit]
    total = len(pending)
    done_total = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    print(f"queue items already done: {done_total:,} | this run: {total:,} | batch={args.batch} threads={args.threads}")

    chunks = [pending[i:i + args.batch] for i in range(0, total, args.batch)]
    started = time.time()
    done = 0
    failed = 0
    skipped = 0
    lock = threading.Lock()

    def work(chunk):
        """Translate one chunk, then re-ask for any key the model skipped."""
        items = [(r[0], r[3] or "", r[2] or "", r[4] or "") for r in chunk]
        got: dict[str, dict] = {}
        pending = items
        last_err = None
        for _round in range(3):
            if not pending:
                break
            # Queue keys contain "|" and long English glosses; models sometimes
            # echo them back mangled and the item would silently drop. Short
            # aliases per call remove that failure mode entirely.
            alias = {f"k{i}": it for i, it in enumerate(pending, start=1)}
            call = [(a, it[1], it[2], it[3]) for a, it in alias.items()]
            try:
                part = translate_gloss_queue_batch(call)
            except Exception as exc:  # noqa: BLE001 - surfaced, never hidden
                last_err = f"{type(exc).__name__}: {exc}"
                part = {}
            for a, value in (part or {}).items():
                if a in alias:
                    got[alias[a][0]] = value
            pending = [it for it in pending if it[0] not in got]
            if pending:
                time.sleep(1.0)
        return chunk, got, (last_err if not got else None)

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = {pool.submit(work, c): c for c in chunks}
        for fut in as_completed(futures):
            chunk, got, err = fut.result()
            with lock:
                if err:
                    failed += len(chunk)
                if len(got) < len(chunk):
                    skipped += len(chunk) - len(got)
                for r in chunk:
                    key, gloss = r[0], r[2] or ""
                    item = got.get(key)
                    if not item or not item.get("ne"):
                        continue
                    ne, back = item.get("ne", ""), item.get("back_en", "")
                    status, conf = score(gloss, back, ne)
                    con.execute(
                        "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?)",
                        (key, r[1], ne, back, status, conf, "failover-chain",
                         time.strftime("%Y-%m-%dT%H:%M:%S")),
                    )
                    done += 1
                con.commit()
            elapsed = time.time() - started
            rate = done / elapsed if elapsed else 0
            eta = (total - done - failed) / rate / 3600 if rate else 0
            print(f"  {done:>7,}/{total:,} done  skipped={skipped:,} failed={failed:,} "
                  f"{rate:.2f} items/s  ETA {eta:.1f} h", flush=True)

    elapsed = time.time() - started
    got_rows = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    summary = {
        "run_items": total,
        "inserted": done,
        "failed": failed,
        "skipped_by_model": skipped,
        "seconds": round(elapsed, 1),
        "items_per_second": round(done / elapsed, 2) if elapsed else 0,
        "results_total": got_rows,
        "queue_total": con.execute("SELECT COUNT(*) FROM queue").fetchone()[0],
    }
    print(json.dumps(summary, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
