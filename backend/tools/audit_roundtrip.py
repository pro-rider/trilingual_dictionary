"""Round-trip audit: for every tagged HSK5 entry, take its own first English
gloss as a search query and check that the lookup returns that same entry.

This is the automated part of "check the whole dictionary again": it measures
whether the meaning a word was imported with is the meaning the app shows.
"""

import json
import re
import sqlite3
import sys

from app.services import sqlite_dataset as sd

DB = r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite"
ARTICLES = ("to ", "a ", "an ", "the ")


def first_query(gloss: str) -> str | None:
    text = (gloss or "").strip()
    if not text:
        return None
    head = re.split(r"[(（]", text, maxsplit=1)[0]
    for seg in re.split(r"[;,/]", head):
        seg = seg.strip().strip(".")
        low = seg.lower()
        for art in ARTICLES:
            if low.startswith(art):
                seg = seg[len(art):]
                break
        seg = seg.strip()
        if 1 <= len(seg.split()) <= 3 and seg:
            return seg
    return None


con = sqlite3.connect(DB)
rows = con.execute(
    "SELECT e.entry_id, e.simplified, e.pinyin_plain, s.gloss_en, s.gloss_ne "
    "FROM entries e JOIN senses s ON s.entry_id = e.entry_id "
    "WHERE e.hsk_level IS NOT NULL AND s.sense_order = 0 "
    "ORDER BY e.entry_id"
).fetchall()

total = ok = skipped = 0
bad = []
for entry_id, simp, pinyin, gloss, ne in rows:
    q = first_query(gloss)
    if not q:
        skipped += 1
        continue
    total += 1
    try:
        res = sd.find_entry(q, "en")
    except Exception as exc:  # noqa: BLE001
        bad.append((q, simp, f"error: {exc}"))
        continue
    if res is None:
        bad.append((q, simp, "no result"))
        continue
    best = res.get("word_zh") or ""
    if best == simp:
        ok += 1
    else:
        first_en = (res.get("word_en") or "")[:20]
        bad.append((q, simp, f"{best} / {first_en}"))

print(f"HSK5 entries with a first sense: {len(rows)}")
print(f"queries run: {total}  exact round-trip: {ok} "
      f"({ok / total * 100:.1f}%)  mismatched: {len(bad)}  skipped: {skipped}")
print()
for q, expected, got in bad[:40]:
    print(f"  {q:24s} expected {expected:8s} got {got}")

with open("data/build/audit.roundtrip.json", "w", encoding="utf-8") as fh:
    json.dump({"total": total, "ok": ok, "bad": bad}, fh, ensure_ascii=False, indent=1)
