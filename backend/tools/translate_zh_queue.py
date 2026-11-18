"""Z-series — build and translate the Chinese gloss queue.

The dictionary ships 123,672 entries but only 13,867 of them carry a Chinese
gloss, so the app shows "Translate now" on almost every word. This tool fills
that gap the same way the Nepali pipeline fills its own: senses are grouped by
(normalised English gloss, domain, and — for ambiguous multi-meaning glosses —
the headword), one Chinese definition is produced per group, and every sense in
the group inherits it.

`enrich_senses_batch` is reused as-is: it already asks the failover chain
(Groq → Gemini → OpenRouter) for a short Chinese definition, a Nepali gloss and
one example sentence in each language, so a Chinese pass also yields example
sentences for senses that have none.

Nothing here writes to `dictionary.sqlite`. Results land in
`data/build/zh_queue.sqlite` and are imported later, after review, by the
import step; AI text must never appear in `senses` unattributed.

Properties:
  * resumable — the queue is built once, `results` is keyed by queue key,
    rerunning skips finished items
  * every result is validated (Han only, length, not the headword itself)
  * failures are recorded, never replaced by an invented value
  * live progress with rate and ETA

Usage:
  .venv\\Scripts\\python.exe tools\\translate_zh_queue.py --build
  .venv\\Scripts\\python.exe tools\\translate_zh_queue.py --limit 30
  .venv\\Scripts\\python.exe tools\\translate_zh_queue.py
  .venv\\Scripts\\python.exe tools\\translate_zh_queue.py --export
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

from app.ai.provider import translate_gloss_zh_batch  # noqa: E402

CJK = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")
DEVANAGARI = re.compile(r"[\u0900-\u097F]")
LATIN = re.compile(r"[A-Za-z]")
WORD_RE = re.compile(r"[a-z0-9']+")
LOCK = threading.Lock()

DEFAULT_DB = Path("data") / "build" / "dictionary.sqlite"
DEFAULT_Q = Path("data") / "build" / "zh_queue.sqlite"


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def build_queue(db_path: Path, out_path: Path, batch_size: int) -> dict:
    """Group every sense that lacks a Chinese gloss."""
    src = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    rows = src.execute(
        """
        SELECT e.simplified, e.pinyin_marked, e.category, e.freq_rank, e.hsk_level,
               s.sense_id, s.gloss_en, s.gloss_ne
          FROM entries e
          JOIN senses s ON s.entry_id = e.entry_id
         WHERE s.gloss_zh IS NULL OR trim(s.gloss_zh) = ''
        """
    ).fetchall()
    src.close()

    groups: dict[str, dict] = {}
    for r in rows:
        gloss_norm = normalise(r["gloss_en"])
        if not gloss_norm:
            continue
        ambiguous = len(re.split(r"[;；/|]", r["gloss_en"] or "")) > 1
        key = f"{gloss_norm}|{(r['category'] or 'general')}"
        if ambiguous:
            key += f"|{r['simplified']}"
        g = groups.get(key)
        rank = r["freq_rank"]
        if g is None:
            groups[key] = {
                "key": key, "gloss": r["gloss_en"], "gloss_norm": gloss_norm,
                "zh": r["simplified"], "pinyin": r["pinyin_marked"] or "",
                "domain": r["category"] or "general", "freq_rank": rank,
                "hsk_level": r["hsk_level"] or "", "senses": 1,
                "sense_ids": [r["sense_id"]],
            }
        else:
            g["senses"] += 1
            g["sense_ids"].append(r["sense_id"])
            if rank is not None and (g["freq_rank"] is None or rank < g["freq_rank"]):
                g["freq_rank"] = rank
                g["zh"] = r["simplified"]
                g["pinyin"] = r["pinyin_marked"] or ""
            if r["hsk_level"] and not g["hsk_level"]:
                g["hsk_level"] = r["hsk_level"]

    ordered = sorted(
        groups.values(),
        key=lambda g: (g["freq_rank"] if g["freq_rank"] is not None else 10**9,
                       -g["senses"], g["key"]),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.execute(
        """
        CREATE TABLE queue (
            key TEXT PRIMARY KEY, batch_id INTEGER, gloss TEXT, gloss_norm TEXT,
            zh TEXT, pinyin TEXT, domain TEXT, freq_rank INTEGER,
            hsk_level TEXT, senses INTEGER, sense_ids TEXT
        )
        """
    )
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    for i, g in enumerate(ordered):
        con.execute(
            "INSERT INTO queue VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (g["key"], i // batch_size, g["gloss"], g["gloss_norm"], g["zh"],
             g["pinyin"], g["domain"], g["freq_rank"], g["hsk_level"],
             g["senses"], json.dumps(g["sense_ids"])),
        )
    stats = {
        "senses_without_zh": len(rows),
        "queue_items": len(ordered),
        "compression_pct": round(100 * (1 - len(ordered) / max(1, len(rows))), 1),
        "batch_size": batch_size,
        "senses_per_item_max": max((g["senses"] for g in ordered), default=0),
    }
    con.executemany("INSERT INTO meta VALUES (?,?)",
                    [(k, json.dumps(v, ensure_ascii=False)) for k, v in stats.items()])
    con.commit()
    con.close()
    out_path.unlink(missing_ok=True)
    tmp.replace(out_path)
    return stats


def tokens(text: str) -> set[str]:
    stop = {"a", "an", "the", "to", "of", "or", "in", "for", "and", "with", "be",
            "is", "are", "that", "this", "someone", "something", "sth", "sb"}
    return {w for w in WORD_RE.findall((text or "").lower()) if w not in stop and len(w) > 1}


def validate(headword: str, gloss: str, zh: str, back_en: str) -> tuple[str, str]:
    """Return (status, confidence) for one Chinese definition."""
    zh = (zh or "").strip()
    if not zh:
        return "empty", "low"
    if not CJK.search(zh):
        return "no_chinese", "low"
    if LATIN.search(zh) or DEVANAGARI.search(zh):
        return "foreign_script", "low"
    if len(zh) > 40:
        return "too_long", "low"
    if len(zh) < 2:
        return "too_short", "low"
    if headword and zh.strip("。؛;， ,") == headword.strip():
        return "echoes_headword", "low"
    g, b = tokens(gloss), tokens(back_en)
    if not b:
        return "ok", "medium"
    if len(g) <= 2:
        return "ok", "high" if (g & b) else "medium"
    overlap = len(g & b) / max(1, len(g | b))
    if overlap >= 0.45:
        return "ok", "high" if 3 <= len(zh) <= 16 else "medium"
    if overlap >= 0.2:
        return "ok", "medium"
    return "backtranslation_mismatch", "low"


def open_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS results (
            key TEXT PRIMARY KEY, zh_def TEXT, ne TEXT, example_en TEXT,
            example_zh TEXT, example_ne TEXT, status TEXT, confidence TEXT,
            model TEXT, translated_at TEXT
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS ix_zh_results_status ON results(status)")
    con.commit()
    return con


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--queue", default=str(DEFAULT_Q))
    ap.add_argument("--build", action="store_true", help="(re)build the queue and exit")
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="only this many items (pilot)")
    ap.add_argument("--max-rank", type=int, default=0,
                    help="only headwords with freq_rank <= N (fill the common words first)")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--exports-dir", default=str(Path("data") / "build" / "reports"))
    args = ap.parse_args()

    qpath = Path(args.queue)
    if args.build or not qpath.exists():
        stats = build_queue(Path(args.db), qpath, args.batch)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        print(f"wrote {qpath}")
        if args.build:
            return 0

    con = open_db(qpath)

    if args.export:
        out = Path(args.exports_dir) / "zh_translations_review.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        rows = con.execute(
            """
            SELECT q.key, q.zh, q.pinyin, q.gloss, q.domain, q.freq_rank, q.hsk_level,
                   q.senses, r.zh_def, r.ne, r.example_en, r.example_zh,
                   r.status, r.confidence
              FROM queue q JOIN results r ON r.key = q.key
             ORDER BY q.freq_rank IS NULL, q.freq_rank, q.key
            """
        ).fetchall()
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["key", "chinese", "pinyin", "gloss_en", "domain", "freq_rank",
                        "hsk", "senses_covered", "zh_definition", "nepali",
                        "example_en", "example_zh", "status", "confidence"])
            w.writerows(rows)
        print(f"wrote {out} ({len(rows)} rows)")
        return 0

    pending = con.execute(
        """
        SELECT q.key, q.zh, q.gloss, q.pinyin, q.freq_rank
          FROM queue q LEFT JOIN results r ON r.key = q.key
         WHERE r.key IS NULL
         ORDER BY q.freq_rank IS NULL, q.freq_rank, q.key
        """
    ).fetchall()
    if args.max_rank:
        pending = [p for p in pending if p[4] is not None and p[4] <= args.max_rank]
    if args.limit:
        pending = pending[: args.limit]
    total = len(pending)
    print(f"queue done: {con.execute('SELECT COUNT(*) FROM results').fetchone()[0]:,} "
          f"| this run: {total:,} | batch={args.batch} threads={args.threads}")

    chunks = [pending[i:i + args.batch] for i in range(0, total, args.batch)]
    started, done, failed = time.time(), 0, 0

    def work(chunk):
        alias = {f"k{i}": row for i, row in enumerate(chunk, start=1)}
        payload = [(a, row[1] or "", row[2] or "") for a, row in alias.items()]
        got, last_err = {}, None
        left = payload
        for _ in range(3):
            if not left:
                break
            try:
                part = translate_gloss_zh_batch(left)
            except Exception as exc:  # noqa: BLE001
                last_err = f"{type(exc).__name__}: {exc}"
                part = {}
            for a, value in (part or {}).items():
                if a in alias:
                    got[alias[a][0]] = value
            left = [p for p in payload if p[0] not in
                    {k for k, row in alias.items() if row[0] in got}]
            if left:
                time.sleep(1.0)
        return chunk, got, (last_err if not got else None)

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = {pool.submit(work, c): c for c in chunks}
        for fut in as_completed(futures):
            chunk, got, err = fut.result()
            with LOCK:
                if err:
                    failed += len(chunk)
                for row in chunk:
                    key, head, gloss = row[0], row[1] or "", row[2] or ""
                    item = got.get(key)
                    if not item or not item.get("zh"):
                        continue
                    status, conf = validate(head, gloss, item.get("zh", ""),
                                            item.get("back_en", ""))
                    con.execute(
                        "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (key, item.get("zh", ""), "", "", "", "",
                         status, conf, "failover-chain",
                         time.strftime("%Y-%m-%dT%H:%M:%S")),
                    )
                    done += 1
                con.commit()
            elapsed = time.time() - started
            rate = done / elapsed if elapsed else 0
            eta = (total - done - failed) / rate / 3600 if rate else 0
            print(f"  {done:>7,}/{total:,} done failed={failed:,} {rate:.2f} items/s "
                  f"ETA {eta:.1f} h", flush=True)

    elapsed = time.time() - started
    summary = {
        "run_items": total, "inserted": done, "failed": failed,
        "seconds": round(elapsed, 1),
        "items_per_second": round(done / elapsed, 2) if elapsed else 0,
        "results_total": con.execute("SELECT COUNT(*) FROM results").fetchone()[0],
        "queue_total": con.execute("SELECT COUNT(*) FROM queue").fetchone()[0],
    }
    print(json.dumps(summary, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
