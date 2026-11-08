"""N4 — build the deduplicated Nepali translation queue.

Groups every sense that still lacks Nepali by (normalised English gloss,
domain), so one gloss is translated once and reused across all entries that
share it. Polysemous glosses stay separate when the Chinese headword differs
*and* the sense would be ambiguous, which is controlled by --split-polysemy.

Part of speech is unusable as a grouping key in this database: CC-CEDICT ships
no POS and `pos_primary` is NULL for 99.96% of senses, so the key falls back to
gloss + domain. The script reports that explicitly instead of silently
pretending POS was part of the key.

Output: `data/build/ne_queue.sqlite`
  queue(key, batch_id, gloss, gloss_norm, zh, pinyin, example, domain, pos,
        freq_rank, hsk_level, senses, sense_ids)
  meta(key, value)

Usage:
  .venv\\Scripts\\python.exe tools\\build_ne_queue.py
  .venv\\Scripts\\python.exe tools\\build_ne_queue.py --batch 30 --out data\\build\\ne_queue.sqlite
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def build(db_path: Path, out_path: Path, batch_size: int, split_polysemy: bool) -> dict:
    src = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    examples = {
        r["sense_id"]: r["en"]
        for r in src.execute(
            "SELECT sense_id, en FROM examples WHERE en IS NOT NULL AND trim(en) <> ''"
        )
    }

    rows = src.execute(
        """
        SELECT e.entry_id, e.simplified, e.pinyin_marked, e.category,
               e.pos_primary, e.freq_rank, e.hsk_level,
               s.sense_id, s.sense_order, s.gloss_en
          FROM entries e
          JOIN senses s ON s.entry_id = e.entry_id
         WHERE s.gloss_ne IS NULL OR trim(s.gloss_ne) = ''
        """
    ).fetchall()
    src.close()

    groups: dict[str, dict] = {}
    for r in rows:
        gloss_norm = normalise(r["gloss_en"])
        if not gloss_norm:
            continue
        # A gloss that carries several meanings is ambiguous on its own; keep
        # the headword in the key so each sense is translated with its context.
        ambiguous = split_polysemy and len(re.split(r"[;；/|]", r["gloss_en"])) > 1
        key = f"{gloss_norm}|{(r['category'] or 'general')}"
        if ambiguous:
            key += f"|{r['simplified']}"
        g = groups.get(key)
        rank = r["freq_rank"]
        if g is None:
            groups[key] = {
                "key": key,
                "gloss": r["gloss_en"],
                "gloss_norm": gloss_norm,
                "zh": r["simplified"],
                "pinyin": r["pinyin_marked"] or "",
                "example": examples.get(r["sense_id"]) or "",
                "domain": r["category"] or "general",
                "pos": r["pos_primary"] or "",
                "freq_rank": rank,
                "hsk_level": r["hsk_level"] or "",
                "senses": 1,
                "sense_ids": [r["sense_id"]],
            }
        else:
            g["senses"] += 1
            g["sense_ids"].append(r["sense_id"])
            if rank is not None and (g["freq_rank"] is None or rank < g["freq_rank"]):
                g["freq_rank"] = rank
                g["zh"] = r["simplified"]
                g["pinyin"] = r["pinyin_marked"] or ""
                g["example"] = examples.get(r["sense_id"]) or ""
            if r["hsk_level"] and not g["hsk_level"]:
                g["hsk_level"] = r["hsk_level"]

    ordered = sorted(
        groups.values(),
        key=lambda g: (g["freq_rank"] if g["freq_rank"] is not None else 10**9,
                       -g["senses"], g["key"]),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    con = sqlite3.connect(out_path)
    con.execute(
        """
        CREATE TABLE queue (
            key TEXT PRIMARY KEY, batch_id INTEGER, gloss TEXT, gloss_norm TEXT,
            zh TEXT, pinyin TEXT, example TEXT, domain TEXT, pos TEXT,
            freq_rank INTEGER, hsk_level TEXT, senses INTEGER, sense_ids TEXT
        )
        """
    )
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    batch_id = 0
    for i, g in enumerate(ordered):
        batch_id = i // batch_size
        con.execute(
            "INSERT INTO queue VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (g["key"], batch_id, g["gloss"], g["gloss_norm"], g["zh"], g["pinyin"],
             g["example"], g["domain"], g["pos"], g["freq_rank"], g["hsk_level"],
             g["senses"], json.dumps(g["sense_ids"])),
        )
    con.execute("CREATE INDEX ix_queue_batch ON queue(batch_id)")

    stats = {
        "senses_without_nepali": len(rows),
        "queue_items": len(ordered),
        "compression_pct": round(100 * (1 - len(ordered) / max(1, len(rows))), 1),
        "batch_size": batch_size,
        "batches": (len(ordered) + batch_size - 1) // batch_size,
        "split_polysemy": split_polysemy,
        "senses_per_item_max": max((g["senses"] for g in ordered), default=0),
        "with_example": sum(1 for g in ordered if g["example"]),
        "with_hsk": sum(1 for g in ordered if g["hsk_level"]),
        "pos_available": sum(1 for g in ordered if g["pos"]),
        "domains": {},
    }
    for g in ordered:
        stats["domains"][g["domain"]] = stats["domains"].get(g["domain"], 0) + 1
    con.executemany("INSERT INTO meta VALUES (?,?)",
                    [(k, json.dumps(v, ensure_ascii=False)) for k, v in stats.items()])
    con.commit()
    con.close()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(Path("data") / "build" / "dictionary.sqlite"))
    ap.add_argument("--out", default=str(Path("data") / "build" / "ne_queue.sqlite"))
    ap.add_argument("--batch", type=int, default=30)
    ap.add_argument("--no-split-polysemy", action="store_true",
                    help="group purely by gloss+domain, ignoring multi-meaning glosses")
    args = ap.parse_args()
    stats = build(Path(args.db), Path(args.out), args.batch, not args.no_split_polysemy)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
