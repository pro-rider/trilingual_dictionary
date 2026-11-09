"""Fill missing Nepali glosses and trilingual example sentences via the LLM chain.

Why this exists
---------------
Two defects come from the same hole in the data:

  * the Nepali box shows "Translate now" because `senses.gloss_ne` is empty
    (195,076 of 198,306 senses); CC-CEDICT only ever had zh + pinyin + English.
  * the example area is blank because `examples` covers 360 of 123,672 entries
    (0.29%).

One `enrich_senses_batch` call returns both: a Nepali gloss and one example
sentence in all three languages. This script runs that call over a resumable
queue and writes the results back with honest provenance:
`ne_status='ai_translated'`, `examples.review_status='unverified'`, so the app
can label them as drafts instead of pretending they were reviewed.

Validation is strict and fails closed — a row is only written when
  * the Nepali gloss and sentence are Devanagari (no Latin, no transliteration),
  * the Chinese sentence has no Hangul / Cyrillic,
  * the English sentence actually contains the English gloss,
  * the sentence is within a sane length window.
Anything else is counted as rejected and can be retried later.

Usage (from backend/):
  .\.venv\Scripts\python.exe tools\gen_examples.py --limit 200 --batch 8
  .\.venv\Scripts\python.exe tools\gen_examples.py --words data\images\seed_words.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.provider import ai_enabled, enrich_senses_batch  # noqa: E402

# Same content-word gate the image pipeline uses: an example sentence for 的 or
# 是 is meaningless as vocabulary practice, and the model can only write a
# sentence about the English gloss, not about the Chinese particle.
from tools.images_v2 import FUNCTION_WORDS, GRAMMAR  # noqa: E402

DEVANAGARI = re.compile(r"[\u0900-\u097F]")
LATIN = re.compile(r"[A-Za-z]")
HAN = re.compile(r"[\u4e00-\u9FFF]")
HANGUL = re.compile(r"[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7AF]")
CYRILLIC = re.compile(r"[\u0400-\u04FF]")
CJK_PUNCT = re.compile(r"[，。！？、；：“”‘’（）]")


def valid_ne(text: str, min_len: int = 2) -> bool:
    if not text or len(text) < min_len:
        return False
    if not DEVANAGARI.search(text):
        return False
    # Latin letters in a Nepali sentence mean the model copied the English.
    if len(LATIN.findall(text)) > 6:
        return False
    return True


def valid_zh(text: str) -> bool:
    return bool(text) and bool(HAN.search(text)) and not HANGUL.search(text) \
        and not CYRILLIC.search(text)


def valid_en(text: str, gloss: str) -> bool:
    if not text or len(text.split()) < 4:
        return False
    root = re.split(r"[;(,]", gloss)[0].strip().lower()
    root = re.sub(r"^to |^a |^an |^the ", "", root)
    if not root:
        return True
    return root.split()[0] in text.lower()


def candidate_senses(con: sqlite3.Connection, words: list[str] | None,
                     limit: int, only_missing: bool,
                     with_images: bool = False) -> list[sqlite3.Row]:
    where = [
        "s.sense_order = 0",
        "s.gloss_en IS NOT NULL",
        "LENGTH(s.gloss_en) BETWEEN 2 AND 60",
        "e.is_proper = 0",
        "e.is_chengyu = 0",
    ]
    args: list = []
    if only_missing:
        where.append("(s.gloss_ne IS NULL OR TRIM(s.gloss_ne) = '')")
    if words:
        where.append("e.simplified IN (%s)" % ",".join("?" * len(words)))
        args = words
    if with_images:
        where.append("EXISTS (SELECT 1 FROM entry_images ei "
                     "WHERE ei.entry_id = e.entry_id)")
    sql = (
        "SELECT s.sense_id, s.entry_id, s.gloss_en, e.simplified, e.pinyin_marked, "
        "       s.gloss_ne "
        "FROM senses s JOIN entries e ON e.entry_id = s.entry_id "
        "WHERE " + " AND ".join(where) +
        " ORDER BY e.freq_rank IS NULL, e.freq_rank, s.sense_id LIMIT ?"
    )
    rows = con.execute(sql, args + [limit * 4]).fetchall()
    kept = []
    for row in rows:
        if row["simplified"] in FUNCTION_WORDS:
            continue
        if GRAMMAR.search(row["gloss_en"] or ""):
            continue
        kept.append(row)
        if len(kept) >= limit:
            break
    return kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/build/dictionary.sqlite")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--words", default="")
    ap.add_argument("--require-example", action="store_true",
                    help="only process senses that have no example row yet")
    ap.add_argument("--with-images", action="store_true",
                    help="only words that already have an approved image")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not ai_enabled():
        print("no LLM provider configured (.env has no usable key)", file=sys.stderr)
        return 1

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    words = None
    if args.words:
        raw = Path(args.words).read_text(encoding="utf-8")
        words = [w.strip() for w in re.split(r"[\n,]+", raw) if w.strip()]

    if args.require_example:
        rows = con.execute(
            "SELECT s.sense_id, s.entry_id, s.gloss_en, e.simplified, s.gloss_ne "
            "FROM senses s JOIN entries e ON e.entry_id = s.entry_id "
            "WHERE s.sense_order = 0 AND s.gloss_en IS NOT NULL "
            "  AND NOT EXISTS (SELECT 1 FROM examples x WHERE x.sense_id = s.sense_id) "
            "ORDER BY e.freq_rank IS NULL, e.freq_rank LIMIT ?", (args.limit,)).fetchall()
    else:
        rows = candidate_senses(con, words, args.limit, only_missing=True,
                                with_images=args.with_images)

    print(f"candidates: {len(rows)}")
    stats = {"ok": 0, "rejected": 0, "empty": 0, "gloss_written": 0, "examples": 0}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for start in range(0, len(rows), args.batch):
        chunk = rows[start:start + args.batch]
        keys = {f"k{i}": row for i, row in enumerate(chunk, 1)}
        items = [(k, r["simplified"], r["gloss_en"]) for k, r in keys.items()]
        try:
            result = enrich_senses_batch(items)
        except Exception as exc:  # noqa: BLE001
            print(f"batch {start}: provider failure ({exc})")
            time.sleep(args.sleep * 3)
            continue
        if not result:
            stats["empty"] += 1
            print(f"batch {start}: empty response (quota or parse failure)")
            time.sleep(args.sleep * 2)
            continue

        for key, payload in result.items():
            row = keys.get(key)
            if row is None:
                continue
            ne = payload.get("ne", "").strip()
            e_en = payload.get("example_en", "").strip()
            e_zh = payload.get("example_zh", "").strip()
            e_ne = payload.get("example_ne", "").strip()
            why = ""
            if not valid_ne(ne) and not valid_ne(e_ne, 6):
                why = "nepali not devanagari"
            elif e_en and not valid_en(e_en, row["gloss_en"]):
                why = "english sentence does not use the gloss"
            elif e_zh and not valid_zh(e_zh):
                why = "chinese sentence invalid"
            elif e_ne and not valid_ne(e_ne, 6):
                why = "nepali sentence invalid"
            if why:
                stats["rejected"] += 1
                print(f"  reject {row['simplified']}: {why}")
                continue

            if args.dry_run:
                print(f"  [dry] {row['simplified']}: ne={ne} | {e_en}")
                stats["ok"] += 1
                continue

            if ne and (not row["gloss_ne"] or not row["gloss_ne"].strip()):
                con.execute(
                    "UPDATE senses SET gloss_ne = ?, ne_status = 'ai_translated' "
                    "WHERE sense_id = ?", (ne, row["sense_id"]))
                stats["gloss_written"] += 1

            if e_en and e_zh and e_ne:
                existing = con.execute(
                    "SELECT example_id FROM examples WHERE sense_id = ?",
                    (row["sense_id"],)).fetchone()
                if existing:
                    con.execute(
                        "UPDATE examples SET en=?, zh=?, ne=?, "
                        "review_status='unverified' WHERE example_id=?",
                        (e_en, e_zh, e_ne, existing[0]))
                else:
                    con.execute(
                        "INSERT INTO examples(sense_id, en, zh, ne, source_id, "
                        "review_status) VALUES (?,?,?,?,NULL,'unverified')",
                        (row["sense_id"], e_en, e_zh, e_ne))
                stats["examples"] += 1
            stats["ok"] += 1

        con.commit()
        print(f"progress {min(start + args.batch, len(rows))}/{len(rows)} "
              f"ok={stats['ok']} gloss={stats['gloss_written']} "
              f"examples={stats['examples']} rejected={stats['rejected']}")
        time.sleep(args.sleep)

    print(json.dumps({
        "generated_at": now, "stats": stats,
        "senses_with_ne": con.execute(
            "SELECT COUNT(*) FROM senses WHERE gloss_ne IS NOT NULL "
            "AND TRIM(gloss_ne) != ''").fetchone()[0],
        "examples": con.execute("SELECT COUNT(*) FROM examples").fetchone()[0],
        "review_status": [tuple(r) for r in con.execute(
            "SELECT review_status, COUNT(*) FROM examples GROUP BY review_status")],
    }, ensure_ascii=False, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
