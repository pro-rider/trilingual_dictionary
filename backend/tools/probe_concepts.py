"""Measure Wikidata concept-resolution hit-rate before building the pipeline.

For the top-N frequent entries: can we resolve the Chinese headword to one
Wikidata entity with an exact label match, and does that entity carry a P18
image? No writes, no downloads.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "build" / "dictionary.sqlite"
UA = "TrilingualDictionary/0.3 (concept probe; lexicography project) python-urllib"
WD = "https://www.wikidata.org/w/api.php"
ENT = "https://www.wikidata.org/w/api.php"


def get_json(url: str, params: dict, timeout: int = 25) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search_entity(term: str, lang: str) -> list[dict]:
    data = get_json(
        ENT,
        {
            "action": "wbsearchentities",
            "search": term,
            "language": lang,
            "uselang": lang,
            "format": "json",
            "limit": "6",
            "type": "item",
        },
    )
    return data.get("search") or []


def entity_claims(qid: str) -> dict:
    data = get_json(
        WD,
        {
            "action": "wbgetentities",
            "ids": qid,
            "format": "json",
            "props": "claims|descriptions|labels|sitelinks",
            "languages": "zh|en",
            "sitefilter": "enwiki|zhwiki",
        },
    )
    return (data.get("entities") or {}).get(qid) or {}


def p18_file(entity: dict) -> str:
    claims = entity.get("claims") or {}
    for claim in claims.get("P18") or []:
        value = (((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value"))
        if isinstance(value, str) and value:
            return value
    return ""


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT e.entry_id, e.simplified, e.category, "
        "(SELECT gloss_en FROM senses s WHERE s.entry_id=e.entry_id "
        " ORDER BY s.sense_order LIMIT 1) AS gloss "
        "FROM entries e WHERE e.is_proper = 0 ORDER BY e.freq_rank LIMIT ?",
        (limit,),
    ).fetchall()

    stats = {"tried": 0, "zh_exact": 0, "en_exact": 0, "none": 0,
             "with_p18": 0, "p18_of_exact": 0}
    t0 = time.time()
    for row in rows:
        stats["tried"] += 1
        word = row["simplified"]
        qid = ""
        method = ""
        hits = search_entity(word, "zh")
        for hit in hits:
            if (hit.get("match") or {}).get("type") == "label" or \
                    (hit.get("label") or "") == word:
                qid, method = hit["id"], "label-zh"
                break
        if not qid:
            term = re.split(r"[;,(]", row["gloss"] or "")[0].strip().lower()
            if term:
                hits = search_entity(term, "en")
                for hit in hits:
                    if (hit.get("label") or "").lower() == term:
                        qid, method = hit["id"], "label-en"
                        break
        if not qid:
            stats["none"] += 1
            print(f"{word:8s} -  no exact concept")
            continue
        stats["zh_exact" if method == "label-zh" else "en_exact"] += 1
        ent = entity_claims(qid)
        stats["p18_of_exact"] += 1
        file_name = p18_file(ent)
        if file_name:
            stats["with_p18"] += 1
        zh_label = ((ent.get("labels") or {}).get("zh") or {}).get("value", "")
        desc = ((ent.get("descriptions") or {}).get("en") or {}).get("value", "")
        print(f"{word:8s} {qid:9s} {method:8s} p18={'Y' if file_name else '-'} "
              f"zh={zh_label[:10]:10s} {desc[:40]}")
        time.sleep(0.35)

    elapsed = time.time() - t0
    print(json.dumps({**stats, "seconds": round(elapsed, 1),
                      "sec_per_word": round(elapsed / max(1, stats["tried"]), 2),
                      "p18_rate": round(stats["with_p18"] / max(1, stats["tried"]), 3)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
