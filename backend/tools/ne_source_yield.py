"""Measure structured-source yield for Nepali on the real launch-gate queue.

Queue = senses in the top 5,000 entries by freq_rank that have no Nepali gloss
and whose English gloss is a plain word or phrase (not a parenthetical grammar
note).

For each target asks two license-clean, machine-checkable sources:
  A) en.wiktionary rendered page -> "Nepali" translation cell
  B) ne.wiktionary full-text search on the gloss -> Devanagari headword
Prints per-target results and the hit rate, and writes a CSV.
"""
import csv
import json
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request

UA = {"User-Agent": "TrilingualDictionaryAgent/0.1 (local dev)"}
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BACKEND, "data", "build", "dictionary.sqlite")
OUT = os.path.join(os.environ.get("TEMP", "."), "ne_source_yield.csv")
DEV = re.compile(r"[\u0900-\u097F]")
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 25


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def wikt_en(gloss):
    word = re.sub(r"[^A-Za-z' -]", "", gloss).strip().split()
    if not word:
        return ""
    title = urllib.parse.quote(word[0].lower())
    try:
        html = json.loads(
            get("https://en.wiktionary.org/w/api.php?action=parse&page=%s&prop=text&format=json&formatversion=2" % title)
        )["parse"]["text"]
    except Exception:
        return ""
    if "Nepali" not in html:
        return ""
    m = re.search(r"Nepali.{0,250}?<dd[^>]*>(.*?)</dd>", html, re.S)
    if not m:
        return ""
    return re.sub(r"<[^>]+>", "", m.group(1)).replace("&#160;", " ").strip()


def wikt_ne(gloss):
    try:
        data = json.loads(
            get(
                "https://ne.wiktionary.org/w/api.php?action=query&generator=search&gsrsearch=%s&gsrlimit=1"
                "&prop=extracts&exintro=1&format=json&formatversion=2" % urllib.parse.quote(gloss)
            )
        )
    except Exception:
        return ""
    for p in (data.get("query") or {}).get("pages") or []:
        if DEV.search(p.get("title", "")):
            return p["title"]
    return ""


def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        """
        select e.simplified, e.pinyin_plain, s.gloss_en, e.freq_rank, e.entry_id, s.sense_id
        from senses s join entries e on e.entry_id = s.entry_id
        where e.freq_rank <= 5000
          and (s.gloss_ne is null or trim(s.gloss_ne) = '')
          and s.gloss_en not like '(%'
          and length(s.gloss_en) < 60
        order by e.freq_rank
        limit ?
        """
        , (LIMIT,)
    ).fetchall()
    print("targets", len(rows))

    out, hits_a, hits_b = [], 0, 0
    for zh, py, gloss, freq, eid, sid in rows:
        va, vb = wikt_en(gloss), wikt_ne(gloss)
        hits_a += bool(va)
        hits_b += bool(vb)
        out.append({"entry_id": eid, "sense_id": sid, "freq_rank": freq, "zh": zh, "pinyin": py,
                    "gloss_en": gloss, "wikt_en_ne": va, "wikt_ne_hit": vb})
        print("%-8s %-26s en=[%s] ne=[%s]" % (zh[:8], gloss[:26], va[:16], vb[:12]))

    if out:
        with open(OUT, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
            w.writeheader()
            w.writerows(out)
    n = len(rows)
    print("A en.wiktionary: %d/%d (%.0f%%)" % (hits_a, n, 100.0 * hits_a / max(1, n)))
    print("B ne.wiktionary: %d/%d (%.0f%%)" % (hits_b, n, 100.0 * hits_b / max(1, n)))
    print("csv", OUT)


if __name__ == "__main__":
    main()
