"""Mine vocabulary from an HSK exam paper and make it answerable in the app.

The paper (H51007) is a scan, so its passages were transcribed to
`data/exam/h51007_passages.txt`. This tool:

1. segments the corpus with jieba and keeps Chinese tokens of 2+ characters;
2. looks every token up in the merged dictionary;
3. records provenance in `corpus_hits` so the source of a word is traceable;
4. for tokens missing from the dictionary, asks the AI for English + pinyin +
   Nepali and inserts them as real entries (status `ai_translated`);
5. fills the missing Nepali gloss for any matched entry (primary sense).

Usage (backend/):
  .venv\\Scripts\\python.exe tools\\import_exam_words.py \\
      --corpus data\\exam\\h51007_passages.txt --db data\\build\\dictionary.sqlite \\
      [--dry-run] [--threads 3]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import jieba

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ai.provider import define_words_batch, nepali_glosses_batch  # noqa: E402

CJK = re.compile(r"[\u4e00-\u9fff]+")
# Function words / fragments jieba emits that are never worth a dictionary entry.
STOP = {
    "一个", "一些", "这个", "那个", "这些", "那些", "我们", "你们", "他们", "她们",
    "自己", "什么", "怎么", "这样", "那样", "因为", "所以", "但是", "而且", "如果",
    "就是", "还是", "已经", "可以", "没有", "不是", "不会", "不能", "不要", "不过",
    "时候", "每天", "一定", "非常", "比较", "出现", "进行", "已经", "起来", "下来",
    "一样", "不同", "问题", "地方", "东西", "人们", "大家", "之后", "以前", "以后",
    "一次", "一点", "有点儿", "一会儿", "有的", "有些人", "当中", "以及", "于是",
}
_TONE_MAP = {
    "ā": "a1", "á": "a2", "ǎ": "a3", "à": "a4", "ē": "e1", "é": "e2", "ě": "e3",
    "è": "e4", "ī": "i1", "í": "i2", "ǐ": "i3", "ì": "i4", "ō": "o1", "ó": "o2",
    "ǒ": "o3", "ò": "o4", "ū": "u1", "ú": "u2", "ǔ": "u3", "ù": "u4", "ǖ": "v1",
    "ǘ": "v2", "ǚ": "v3", "ǜ": "v4", "ń": "n2", "ň": "n3", "ǹ": "n4",
}


def marked_to_num(pinyin: str) -> str:
    return "".join(_TONE_MAP.get(ch, ch) for ch in pinyin)


def plain_pinyin(pinyin: str) -> str:
    d = unicodedata.normalize("NFD", pinyin)
    return "".join(c for c in d if not unicodedata.combining(c)).replace("ü", "v").lower()


def tokens(text: str) -> list[str]:
    body = CJK.findall(text)
    blob = "".join(body)
    out: list[str] = []
    seen: set[str] = set()
    for tok in jieba.cut(blob):
        tok = tok.strip()
        if len(tok) < 2 or not CJK.fullmatch(tok) or tok in STOP or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/exam/h51007_passages.txt")
    ap.add_argument("--db", default="data/build/dictionary.sqlite")
    ap.add_argument("--threads", type=int, default=3)
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default="data/build/exam_h51007.report.json")
    args = ap.parse_args()

    started = time.time()
    text = Path(args.corpus).read_text(encoding="utf-8")
    toks = tokens(text)
    print(f"corpus tokens: {len(toks)}")

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE IF NOT EXISTS corpus_hits ("
        " entry_id INTEGER NOT NULL, corpus TEXT NOT NULL,"
        " hits INTEGER NOT NULL DEFAULT 0,"
        " PRIMARY KEY (entry_id, corpus))"
    )

    matched: dict[str, int] = {}
    missing: list[str] = []
    for tok in toks:
        row = con.execute(
            "SELECT entry_id FROM entries WHERE simplified = ? LIMIT 1", (tok,)
        ).fetchone()
        if row:
            matched[tok] = row["entry_id"]
        else:
            missing.append(tok)
    print(f"in dictionary: {len(matched)}   missing: {len(missing)}")
    if args.dry_run:
        report = {"tokens": len(toks), "matched": len(matched),
                  "missing": len(missing), "missing_words": missing}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    # provenance for every word the paper actually uses
    for tok, entry_id in matched.items():
        con.execute(
            "INSERT INTO corpus_hits(entry_id, corpus, hits) VALUES (?,?,1) "
            "ON CONFLICT(entry_id, corpus) DO UPDATE SET hits = hits + 1",
            (entry_id, "HSK5-H51007"),
        )
    con.commit()

    created = 0
    skipped = 0
    if missing:
        definitions: dict[str, dict[str, str]] = {}
        for start in range(0, len(missing), args.batch):
            chunk = missing[start:start + args.batch]
            definitions.update(define_words_batch(chunk))
        for word in missing:
            info = definitions.get(word)
            if not info or not info.get("en"):
                continue
            if info.get("is_word") is False:
                skipped += 1
                continue
            pinyin = info.get("pinyin") or ""
            pnum = marked_to_num(pinyin)
            plain = plain_pinyin(pinyin)
            cur = con.execute(
                "INSERT INTO entries(simplified, traditional, pinyin_num, pinyin_marked,"
                " pinyin_plain, pinyin_search, category, pos_primary, rarity,"
                " freq_rank, hsk_level, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (word, word, pnum, pinyin, plain,
                 f"{plain.replace(' ', '')} {plain}", "general",
                 info.get("pos", ""), None, None, None, "ai_translated"),
            )
            entry_id = cur.lastrowid
            cur = con.execute(
                "INSERT INTO senses(entry_id, sense_order, gloss_en, gloss_zh,"
                " gloss_ne, ne_status, source_id) VALUES (?,?,?,?,?,?,?)",
                (entry_id, 0, info["en"], None, info.get("ne") or None,
                 "ai_translated" if info.get("ne") else "none", None),
            )
            con.execute(
                "INSERT INTO fts(simplified, traditional, pinyin_search, english,"
                " category, entry_id) VALUES (?,?,?,?,?,?)",
                (word, word, f"{plain.replace(' ', '')} {plain}", info["en"],
                 "general", entry_id),
            )
            con.execute(
                "INSERT INTO corpus_hits(entry_id, corpus, hits) VALUES (?,?,1) "
                "ON CONFLICT(entry_id, corpus) DO UPDATE SET hits = hits + 1",
                (entry_id, "HSK5-H51007"),
            )
            created += 1
        con.commit()
    print(f"created from paper: {created}")

    # Nepali for matched entries that have none yet (primary sense only)
    placeholders = ",".join("?" * len(matched))
    query = (
        "SELECT s.sense_id, s.gloss_en FROM entries e "
        "JOIN senses s ON s.entry_id = e.entry_id "
        f"WHERE e.simplified IN ({placeholders}) AND s.sense_order = 0 "
        "AND (s.gloss_ne IS NULL OR s.gloss_ne = '')"
    )
    rows = con.execute(query, list(matched.keys())).fetchall()
    todo = [(str(r["sense_id"]), r["gloss_en"]) for r in rows if r["gloss_en"]]
    print(f"nepali to translate: {len(todo)}")

    translated: dict[str, str] = {}
    chunks = [todo[i:i + args.batch] for i in range(0, len(todo), args.batch)]
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = [pool.submit(nepali_glosses_batch, c) for c in chunks]
        for fut in as_completed(futures):
            try:
                got = fut.result()
            except Exception as exc:
                print(f"  batch error: {exc}")
                got = {}
            translated.update(got)
            for sense_id, ne in got.items():
                con.execute(
                    "UPDATE senses SET gloss_ne = ?, ne_status = 'ai_translated' "
                    "WHERE sense_id = ?", (ne, int(sense_id)))
            con.commit()
            print(f"  nepali {len(translated)}/{len(todo)}")

    report = {
        "corpus": Path(args.corpus).name,
        "tokens": len(toks),
        "matched": len(matched),
        "missing": len(missing),
        "created": created,
        "skipped_fragments": skipped,
        "ne_filled": len(translated),
        "ne_failed": len(todo) - len(translated),
        "elapsed_s": round(time.time() - started, 1),
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
