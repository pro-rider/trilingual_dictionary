"""Generate example sentences for launch-set senses, into a candidate table.

Priority order from the brief: licensed corpus data available offline > AI
generation > leave empty. There is no sentence corpus in the database
(`corpus_hits` only stores counts), so this tool uses the one working provider
and writes every sentence to `example_candidates` with
`status='pending_review'`. Nothing here reaches `examples` — a human decision
in the review file does that (rule 2).

Every sentence must pass `validate()`: it has to contain the headword, be in the
right language, have a sensible length, and contain none of the blocked words.

    python tools/gen_example_sentences.py --limit 8 --dry-run
    python tools/gen_example_sentences.py --limit 800
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB = REPO_ROOT / "backend" / "data" / "build" / "dictionary.sqlite"
ENV = REPO_ROOT / "backend" / ".env"

SYSTEM = (
    "You write example sentences for a learner's Chinese dictionary "
    "(Chinese / English / Nepali). For each item you get the headword, its pinyin "
    "and its English gloss. Produce one natural, short sentence per item:\n"
    "  zh: a Chinese sentence (8-25 characters) that uses the headword exactly as "
    "written, in its most common everyday sense. Simplified characters only.\n"
    "  en: the faithful English translation of that Chinese sentence.\n"
    "  ne: the faithful Nepali translation in Devanagari script.\n"
    "Rules: no proper nouns invented, no violence, no politics, no adult content, "
    "no textbook stiffness. The headword must appear character-for-character. "
    "Return ONLY a JSON array: "
    '[{"sid": <sense id as given>, "zh": "...", "en": "...", "ne": "..."}]'
)

DEVANAGARI = re.compile(r"[\u0900-\u097F]")
CJK = re.compile(r"[\u4e00-\u9fff]")
BLOCKED = (
    "kill", "murder", "suicide", "rape", "sex", "porn", "drug", "gun", "bomb",
    "terror", "nigger", "fuck", "shit",
    "杀", "自杀", "强奸", "色情", "毒品", "炸弹", "恐怖",
)

DDL = """
CREATE TABLE IF NOT EXISTS example_candidates (
  candidate_id INTEGER PRIMARY KEY,
  sense_id    INTEGER NOT NULL,
  entry_id    INTEGER NOT NULL,
  headword    TEXT NOT NULL,
  zh          TEXT,
  en          TEXT,
  ne          TEXT,
  generator   TEXT NOT NULL,
  source      TEXT NOT NULL,
  license     TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending_review',
  reject_reason TEXT,
  created_at  TEXT NOT NULL
)
"""


def load_env() -> dict:
    out = {}
    if not ENV.exists():
        return out
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def validate(headword: str, zh: str, en: str, ne: str) -> str | None:
    """Return a rejection reason, or None when the sentence is acceptable."""
    zh, en, ne = (zh or "").strip(), (en or "").strip(), (ne or "").strip()
    if not headword or not zh or not en or not ne:
        return "empty_field"
    if headword not in zh:
        return "headword_missing_from_chinese"
    if not (6 <= len(zh) <= 45):
        return "chinese_length"
    if not CJK.search(zh):
        return "chinese_not_chinese"
    if not (8 <= len(en) <= 120):
        return "english_length"
    if CJK.search(en):
        return "chinese_inside_english"
    if not DEVANAGARI.search(ne):
        return "nepali_not_devanagari"
    if not (8 <= len(ne) <= 160):
        return "nepali_length"
    lowered = f"{zh} {en} {ne}".lower()
    for word in BLOCKED:
        if word in lowered:
            return f"blocked_content:{word}"
    return None


def extract_array(text: str) -> list:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.S)
        if not match:
            raise ValueError("no JSON array in response")
        data = json.loads(match.group(0))
    if isinstance(data, dict):
        for key in ("items", "data", "sentences", "results"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data


def call_openrouter(cfg: dict, payload_items: list, model: str,
                    max_tokens: int = 1600) -> list:
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps({"items": payload_items},
                                                  ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {cfg['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/pro-rider/trilingual_dictionary",
            "X-Title": "trilingual-dictionary-examples",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read())
    return extract_array(body["choices"][0]["message"]["content"])


def pending_senses(con: sqlite3.Connection, limit: int) -> list:
    rows = con.execute(
        """
        SELECT s.sense_id, s.entry_id, e.simplified, e.pinyin_marked, s.gloss_en
        FROM senses s
        JOIN entries e USING(entry_id)
        JOIN launch_set l USING(entry_id)
        WHERE l.tier <= 2
          AND s.sense_id NOT IN (SELECT sense_id FROM examples)
          AND s.sense_id NOT IN (SELECT sense_id FROM example_candidates)
        ORDER BY l.tier, e.freq_rank IS NULL, e.freq_rank, s.sense_id
        """
    ).fetchall()
    return rows[:limit] if limit else rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--model", default="meta-llama/llama-3.1-70b-instruct")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--max-tokens", type=int, default=1600)
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args(argv)

    cfg = load_env()
    if not cfg.get("OPENROUTER_API_KEY"):
        sys.exit("OPENROUTER_API_KEY missing in backend/.env")

    con = sqlite3.connect(args.db)
    con.executescript(DDL)
    todo = pending_senses(con, args.limit)
    print(f"senses to fill: {len(todo)} (batch={args.batch})")
    if not todo:
        return 0

    stored = 0
    rejected: dict[str, int] = {}
    failed = 0
    t0 = time.time()
    for start in range(0, len(todo), args.batch):
        batch = todo[start : start + args.batch]
        items = [
            {"sid": sid, "w": word, "pinyin": pinyin, "gloss": gloss}
            for sid, _eid, word, pinyin, gloss in batch
        ]
        response = None
        for attempt in range(3):
            try:
                response = call_openrouter(cfg, items, args.model, args.max_tokens)
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:160]
                print(f"[warn] HTTP {exc.code} {detail}")
                time.sleep(8 * (attempt + 1))
            except Exception as exc:
                print(f"[warn] {type(exc).__name__}: {exc}")
                time.sleep(3 * (attempt + 1))
        if response is None:
            failed += len(batch)
            continue

        by_sid = {}
        for item in response:
            try:
                sid = int(item.get("sid"))
            except (TypeError, ValueError):
                rejected["bad_sid"] = rejected.get("bad_sid", 0) + 1
                continue
            by_sid[sid] = item
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for sid, eid, word, _pinyin, _gloss in batch:
            item = by_sid.get(sid)
            if item is None:
                failed += 1
                continue
            zh = str(item.get("zh", "")).strip()
            en = str(item.get("en", "")).strip()
            ne = str(item.get("ne", "")).strip()
            reason = validate(word, zh, en, ne)
            if reason:
                rejected[reason] = rejected.get(reason, 0) + 1
                if not args.dry_run:
                    con.execute(
                        "INSERT INTO example_candidates (sense_id, entry_id, headword, "
                        "zh, en, ne, generator, source, license, status, reject_reason, "
                        "created_at) VALUES (?,?,?,?,?,?,?,'ai_generation',"
                        "'machine-generated (unlicensed output)', 'pending_review',?,?)",
                        (sid, eid, word, zh, en, ne, args.model, reason, now),
                    )
                continue
            rows.append((sid, eid, word, zh, en, ne, args.model, now))
        if rows and not args.dry_run:
            con.executemany(
                "INSERT INTO example_candidates (sense_id, entry_id, headword, zh, en, "
                "ne, generator, source, license, status, created_at) VALUES "
                "(?,?,?,?,?,?,?,'ai_generation',"
                "'machine-generated (unlicensed output)','pending_review',?)",
                rows,
            )
        if not args.dry_run:
            con.commit()
        stored += len(rows)
        if args.dry_run:
            for row in rows[:3]:
                print(f"  {row[2]}: {row[3]} | {row[4]} | {row[5]}")
        print(f"[{start + len(batch):>5}/{len(todo)}] stored={stored} "
              f"rejected={sum(rejected.values())} failed={failed} "
              f"elapsed={time.time() - t0:.0f}s", flush=True)
        if args.sleep:
            time.sleep(args.sleep)

    print(json.dumps({"stored": stored, "rejected": rejected, "failed": failed,
                      "dry_run": args.dry_run}, ensure_ascii=False, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
