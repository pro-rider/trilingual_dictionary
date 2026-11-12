"""Generate English + Nepali glosses for the remaining new words, via OpenRouter.

Writes only to `words3000_candidates` (a staging table), never to `entries` or
`senses`: the Nepali produced here is machine text that a native speaker must
review first (rule 2 in the brief). Rows are marked `status='glossed_ai'` so they
can never be confused with the 320 rows that came from the human batch.

Resume-safe: words that already hold both glosses are skipped, so a crashed or
rate-limited run is simply re-run.

    python tools/gen_new_word_gloss.py --limit 20 --dry-run
    python tools/gen_new_word_gloss.py
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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB = REPO_ROOT / "backend" / "data" / "build" / "dictionary.sqlite"
ENV = REPO_ROOT / "backend" / ".env"
LOG = REPO_ROOT / "docs" / "gloss_gen_log.jsonl"

SYSTEM = (
    "You are a lexicographer for a trilingual learner's dictionary "
    "(English / Chinese / Nepali). For each Chinese headword you receive, return:\n"
    "  en: a concise English gloss, dictionary style, 2-10 words, no trailing period.\n"
    "  ne: the standard Nepali equivalent in Devanagari script, dictionary style, "
    "short noun/verb phrase, no full sentence, no transliteration of the Chinese.\n"
    "Rules: never invent a meaning; if the headword is an uncommon technical compound, "
    "gloss it literally and accurately from its parts. Every field must be non-empty. "
    "Return ONLY a JSON array, one object per input word: "
    '[{"w": "<headword exactly as given>", "en": "...", "ne": "..."}]'
)

DEVANAGARI = re.compile(r"[\u0900-\u097F]")
CJK = re.compile(r"[\u4e00-\u9fff]")


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


def extract_array(text: str) -> list:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            raise ValueError("no JSON array in response")
        data = json.loads(m.group(0))
    if isinstance(data, dict):
        for key in ("items", "data", "words", "result", "results"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data


def call_openrouter(cfg: dict, words: list[str], model: str) -> list:
    payload = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 1200,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps({"words": words}, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {cfg['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/pro-rider/trilingual_dictionary",
            "X-Title": "trilingual-dictionary-gloss-gen",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read())
    return extract_array(body["choices"][0]["message"]["content"])


def valid(en: str, ne: str) -> str | None:
    """Return a rejection reason, or None when the pair is usable."""
    if not en or not ne:
        return "empty_field"
    if CJK.search(en):
        return "chinese_inside_english"
    if not DEVANAGARI.search(ne):
        return "nepali_not_devanagari"
    if len(en) > 120 or len(ne) > 120:
        return "too_long"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only the first N pending words")
    ap.add_argument("--batch", type=int, default=15)
    ap.add_argument("--model", default="meta-llama/llama-3.1-70b-instruct")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=2.0, help="pause between batches")
    args = ap.parse_args(argv)

    cfg = load_env()
    if not cfg.get("OPENROUTER_API_KEY"):
        sys.exit("OPENROUTER_API_KEY missing in backend/.env")

    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT word FROM words3000_candidates "
        "WHERE (gloss_en IS NULL OR trim(gloss_en)='' OR gloss_ne IS NULL "
        "       OR trim(gloss_ne)='') "
        "ORDER BY char_count, word"
    ).fetchall()
    words = [r[0] for r in rows]
    if args.limit:
        words = words[: args.limit]
    print(f"pending words: {len(words)} (batch={args.batch}, model={args.model})")

    done = 0
    rejected: dict[str, int] = {}
    failed: list[str] = []
    t0 = time.time()
    for start in range(0, len(words), args.batch):
        batch = words[start : start + args.batch]
        items = None
        for attempt in range(3):
            try:
                items = call_openrouter(cfg, batch, args.model)
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:200]
                print(f"[warn] batch {start}: HTTP {exc.code} {detail}")
                if exc.code in (402, 403, 404, 429):
                    time.sleep(10 * (attempt + 1))
                else:
                    time.sleep(3 * (attempt + 1))
            except Exception as exc:
                print(f"[warn] batch {start}: {type(exc).__name__}: {exc}")
                time.sleep(3 * (attempt + 1))
        if items is None:
            failed.extend(batch)
            continue

        updates = []
        for item in items:
            w = str(item.get("w") or item.get("word") or "").strip()
            en = str(item.get("en") or item.get("english") or "").strip().rstrip(".")
            ne = str(item.get("ne") or item.get("nepali") or "").strip()
            if w not in batch:
                rejected["unknown_word_returned"] = rejected.get("unknown_word_returned", 0) + 1
                continue
            reason = valid(en, ne)
            if reason:
                rejected[reason] = rejected.get(reason, 0) + 1
                failed.append(w)
                continue
            updates.append((en, ne, w))
        if updates and not args.dry_run:
            con.executemany(
                "UPDATE words3000_candidates SET gloss_en=?, gloss_ne=?, "
                "status='glossed_ai' WHERE word=?",
                updates,
            )
            con.commit()
        done += len(updates)
        if args.dry_run and updates:
            for en, ne, w in updates[:3]:
                print(f"  {w}: {en} / {ne}")
        print(f"[{start + len(batch):>5}/{len(words)}] ok={done} failed={len(failed)} "
              f"elapsed={time.time() - t0:.0f}s", flush=True)
        if args.sleep:
            time.sleep(args.sleep)

    summary = {"done": done, "failed": len(failed), "rejected": rejected,
               "failed_sample": failed[:20], "model": args.model,
               "dry_run": args.dry_run}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False) + "\n")
    con.close()
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
