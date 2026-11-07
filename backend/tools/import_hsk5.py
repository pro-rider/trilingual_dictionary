"""Import the official HSK5 (2500-word) list into the dictionary database.

Source: 新HSK5词汇表（汉英）.pdf — three columns of `N． / pinyin / 汉字`. The PDF
carries no English gloss, so English comes from CC-CEDICT (already imported);
Nepali is generated in batches and stored as `ne_status = 'ai_translated'`.

Nothing is duplicated: a headword that already exists is only *marked* HSK5 and
gets its missing Nepali gloss filled. Headwords absent from CC-CEDICT are created
new (status `ai_translated`) with AI-supplied English/pinyin/Nepali.

Usage (from backend/, backend stopped so SQLite is not contended):
  .venv\\Scripts\\python.exe tools\\import_hsk5.py --pdf <path> \\
      --db data\\build\\dictionary.sqlite [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import sqlite3
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ai.provider import define_words_batch, nepali_glosses_batch  # noqa: E402

CJK = re.compile(r"[\u4e00-\u9fff]+")
NUMBER = re.compile(r"^\s*(\d{1,4})\s*[．.]")
POS_HINT = re.compile(r"（(.+?)）")
LATIN = re.compile(r"[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüńňǹ\s'’]+")

_TONE_MAP = {
    "ā": "a1", "á": "a2", "ǎ": "a3", "à": "a4",
    "ē": "e1", "é": "e2", "ě": "e3", "è": "e4",
    "ī": "i1", "í": "i2", "ǐ": "i3", "ì": "i4",
    "ō": "o1", "ó": "o2", "ǒ": "o3", "ò": "o4",
    "ū": "u1", "ú": "u2", "ǔ": "u3", "ù": "u4",
    "ǖ": "v1", "ǘ": "v2", "ǚ": "v3", "ǜ": "v4",
    "ń": "n2", "ň": "n3", "ǹ": "n4",
}


@dataclass
class Item:
    num: int
    pinyin: str  # tone marks, spaces removed
    word: str
    pos_hint: str


def marked_to_num(pinyin: str) -> str:
    out = []
    for ch in pinyin:
        if ch in _TONE_MAP:
            out.append(_TONE_MAP[ch])
        elif ch == " ":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def plain_pinyin(pinyin: str) -> str:
    decomposed = unicodedata.normalize("NFD", pinyin)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.replace("ü", "v").lower()


def parse_pdf(pdf: Path) -> list[Item]:
    """Three-line rhythm: number → pinyin → hanzi (optionally with （动）)."""
    reader = PdfReader(str(pdf))
    items: list[Item] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lines = [ln.strip() for ln in text.splitlines()]
        i = 0
        while i < len(lines):
            m = NUMBER.match(lines[i])
            if not m:
                i += 1
                continue
            num = int(m.group(1))
            # next line with latin/pinyin characters
            pinyin = ""
            j = i + 1
            while j < len(lines) and not pinyin:
                cand = lines[j]
                if LATIN.fullmatch(cand.replace(" ", "")) and cand and not CJK.search(cand):
                    pinyin = cand.replace(" ", "")
                j += 1
            # next line containing hanzi
            word = ""
            pos_hint = ""
            while j < len(lines) and not word:
                cand = lines[j]
                found = CJK.search(cand)
                if found:
                    word = found.group(0)
                    hint = POS_HINT.search(cand)
                    if hint:
                        pos_hint = hint.group(1).strip()
                j += 1
            if num and pinyin and word:
                items.append(Item(num, pinyin, word, pos_hint))
                i = j
            else:
                i += 1
    return items


def pick_entry(con: sqlite3.Connection, word: str, pinyin: str) -> int | None:
    rows = con.execute(
        "SELECT entry_id, pinyin_plain, pinyin_marked FROM entries "
        "WHERE simplified = ?",
        (word,),
    ).fetchall()
    if not rows:
        return None
    target_plain = plain_pinyin(pinyin).replace(" ", "")
    for entry_id, e_plain, e_marked in rows:
        if (e_plain or "").replace(" ", "") == target_plain:
            return entry_id
    for entry_id, e_plain, _ in rows:
        if (e_plain or "").replace(" ", "") in {target_plain, target_plain.replace("v", "u")}:
            return entry_id
    return rows[0][0]


def _translate_chunk(chunk: list[tuple[str, str]]) -> dict[str, str]:
    """One batch, one retry. Never raises: a failed batch is retried next run."""
    for _attempt in range(2):
        try:
            got = nepali_glosses_batch(chunk)
        except Exception as exc:  # provider or JSON-shape problem
            print(f"  batch error: {exc}", flush=True)
            got = {}
        if got:
            return got
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--db", default="data/build/dictionary.sqlite")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=30)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--all-senses", dest="primary_only", action="store_false",
                    help="translate every sense, not just the primary one")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default="data/build/hsk5_import.report.json")
    args = ap.parse_args()

    started = time.time()
    items = parse_pdf(Path(args.pdf))
    if args.limit:
        items = items[: args.limit]
    print(f"parsed {len(items)} items; unique headwords {len({i.word for i in items})}")

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    report = {
        "items": len(items),
        "matched": 0,
        "created": 0,
        "ne_filled": 0,
        "ne_failed": 0,
        "dry_run": bool(args.dry_run),
    }

    # 1) classify every headword: existing entry vs brand-new
    pending_new: list[Item] = []
    matched: list[tuple[Item, int]] = []
    for item in items:
        if args.dry_run:
            continue
        entry_id = pick_entry(con, item.word, item.pinyin)
        if entry_id is None:
            pending_new.append(item)
        else:
            matched.append((item, entry_id))
    report["matched"] = len(matched)

    if args.dry_run:
        known = unknown = 0
        for item in items:
            if pick_entry(con, item.word, item.pinyin) is None:
                unknown += 1
            else:
                known += 1
        report["known_in_cedict"] = known
        report["unknown_in_cedict"] = unknown
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    # 2) mark existing entries as HSK5
    for _item, entry_id in matched:
        con.execute("UPDATE entries SET hsk_level = 5 WHERE entry_id = ?", (entry_id,))
    con.commit()

    # 3) create genuinely new headwords from AI definitions
    if pending_new:
        definitions: dict[str, dict[str, str]] = {}
        words = [i.word for i in pending_new]
        for start in range(0, len(words), args.batch):
            chunk = words[start:start + args.batch]
            definitions.update(define_words_batch(chunk))
            print(f"  definitions {min(start + args.batch, len(words))}/{len(words)}", flush=True)
        for item in pending_new:
            info = definitions.get(item.word)
            if not info or not info.get("en"):
                continue
            pinyin_marked = info.get("pinyin") or item.pinyin
            pinyin_num = marked_to_num(pinyin_marked) if info.get("pinyin") else marked_to_num(item.pinyin)
            plain = plain_pinyin(pinyin_marked)
            cur = con.execute(
                "INSERT INTO entries(simplified, traditional, pinyin_num, pinyin_marked,"
                " pinyin_plain, pinyin_search, category, pos_primary, rarity,"
                " freq_rank, hsk_level, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (item.word, item.word, pinyin_num, pinyin_marked, plain,
                 f"{plain.replace(' ', '')} {plain}", "general",
                 info.get("pos", ""), None, None, 5, "ai_translated"),
            )
            entry_id = cur.lastrowid
            cur = con.execute(
                "INSERT INTO senses(entry_id, sense_order, gloss_en, gloss_zh,"
                " gloss_ne, ne_status, source_id) VALUES (?,?,?,?,?,?,?)",
                (entry_id, 0, info["en"], None, info.get("ne") or None,
                 "ai_translated" if info.get("ne") else "none", None),
            )
            sense_id = cur.lastrowid
            con.execute(
                "INSERT INTO fts(simplified, traditional, pinyin_search, english,"
                " category, entry_id) VALUES (?,?,?,?,?,?)",
                (item.word, item.word, f"{plain.replace(' ', '')} {plain}",
                 info["en"], "general", entry_id),
            )
            report["created"] += 1
            if info.get("ne"):
                report["ne_filled"] += 1
        con.commit()
        print(f"created {report['created']} new entries", flush=True)

    # 4) fill missing Nepali for the HSK5 senses.
    # Primary sense first: that is the meaning a learner needs, and translating
    # 2,500 primary senses is ~15 min instead of ~2 h for all 7,447.
    rows = con.execute(
        "SELECT e.entry_id, s.sense_id, s.gloss_en, s.sense_order FROM entries e "
        "JOIN senses s ON s.entry_id = e.entry_id "
        "WHERE e.hsk_level = 5 AND (s.gloss_ne IS NULL OR s.gloss_ne = '') "
        "ORDER BY s.sense_order = 0 DESC, e.entry_id"
    ).fetchall()
    if args.primary_only:
        rows = [r for r in rows if r["sense_order"] == 0]
    todo = [(str(r["sense_id"]), r["gloss_en"]) for r in rows if r["gloss_en"]]
    print(f"nepali to translate: {len(todo)}", flush=True)

    chunks = [todo[i:i + args.batch] for i in range(0, len(todo), args.batch)]
    translated: dict[str, str] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = [pool.submit(_translate_chunk, chunk) for chunk in chunks]
        for fut in as_completed(futures):
            got = fut.result()
            translated.update(got)
            done += len(got)
            # persist incrementally: an interrupt never loses paid work
            for sense_id, ne in got.items():
                con.execute(
                    "UPDATE senses SET gloss_ne = ?, ne_status = 'ai_translated' "
                    "WHERE sense_id = ?",
                    (ne, int(sense_id)),
                )
            con.commit()
            print(f"  nepali {done}/{len(todo)}", flush=True)
    report["ne_filled"] += len(translated)
    report["ne_failed"] = len(todo) - len(translated)
    con.commit()

    report["elapsed_s"] = round(time.time() - started, 1)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
