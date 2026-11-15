"""Concept layer, stage 0 (read-only plan): how far could a *concept* image pack go?

The release DB has 109 approved images for 123,672 entries. The reason is not the
pipeline (`tools/fetch_images.py` already fetches Commons/Wikipedia with a licence
gate) but the unit of work: one image per *word* can only ever cover a handful.
This tool measures the alternative: one image per *visual concept*, inherited by
every headword that means that concept.

No writes to any dictionary. Reads only. Writes two CSVs under `review/`:

  review/image_concepts.csv          concept -> how many top-N entries it would cover
  review/image_concepts_unmapped.csv top-N words with no visual concept (abstract)

Usage
-----
  python tools/image_concept_plan.py --db data/build/dictionary.sqlite --top 3000
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A deliberately small, concrete lexicon: things a photograph can actually show.
# English keywords match the first gloss; zh chars match a single-character
# headword. Extend by review, never by automatic translation.
LEXICON: dict[str, dict[str, object]] = {
    # animals
    "cat": {"en": ["cat", "kitten"], "zh": "猫"},
    "dog": {"en": ["dog", "puppy"], "zh": "狗"},
    "bird": {"en": ["bird"], "zh": "鸟"},
    "fish": {"en": ["fish"], "zh": "鱼"},
    "horse": {"en": ["horse"], "zh": "马"},
    "cow": {"en": ["cow", "cattle", "ox"], "zh": "牛"},
    "sheep": {"en": ["sheep", "goat"], "zh": "羊"},
    "pig": {"en": ["pig", "hog"], "zh": "猪"},
    "chicken": {"en": ["chicken", "hen", "rooster"], "zh": "鸡"},
    "mouse": {"en": ["mouse", "rat"], "zh": "鼠"},
    "rabbit": {"en": ["rabbit", "hare"], "zh": "兔"},
    "tiger": {"en": ["tiger"], "zh": "虎"},
    "monkey": {"en": ["monkey"], "zh": "猴"},
    "snake": {"en": ["snake", "serpent"], "zh": "蛇"},
    "bear": {"en": ["bear"], "zh": "熊"},
    "elephant": {"en": ["elephant"], "zh": "象"},
    "wolf": {"en": ["wolf"], "zh": "狼"},
    "duck": {"en": ["duck"], "zh": "鸭"},
    # food / drink
    "rice": {"en": ["rice"], "zh": "米"},
    "noodle": {"en": ["noodle"], "zh": "面"},
    "bread": {"en": ["bread"], "zh": "面包"},
    "apple": {"en": ["apple"], "zh": "苹果"},
    "banana": {"en": ["banana"], "zh": "香蕉"},
    "egg": {"en": ["egg"], "zh": "蛋"},
    "milk": {"en": ["milk"], "zh": "奶"},
    "tea": {"en": ["tea"], "zh": "茶"},
    "water": {"en": ["water"], "zh": "水"},
    "wine": {"en": ["wine"], "zh": "酒"},
    "meat": {"en": ["meat", "beef", "pork"], "zh": "肉"},
    "fruit": {"en": ["fruit"], "zh": "水果"},
    "vegetable": {"en": ["vegetable"], "zh": "菜"},
    "sugar": {"en": ["sugar"], "zh": "糖"},
    "salt": {"en": ["salt"], "zh": "盐"},
    "coffee": {"en": ["coffee"], "zh": "咖啡"},
    # body
    "hand": {"en": ["hand"], "zh": "手"},
    "head": {"en": ["head"], "zh": "头"},
    "eye": {"en": ["eye"], "zh": "眼"},
    "ear": {"en": ["ear"], "zh": "耳"},
    "nose": {"en": ["nose"], "zh": "鼻"},
    "mouth": {"en": ["mouth"], "zh": "嘴"},
    "tooth": {"en": ["tooth", "teeth"], "zh": "牙"},
    "finger": {"en": ["finger"], "zh": "指"},
    "foot": {"en": ["foot", "feet"], "zh": "脚"},
    "leg": {"en": ["leg"], "zh": "腿"},
    "arm": {"en": ["arm"], "zh": "臂"},
    "hair": {"en": ["hair"], "zh": "发"},
    "heart": {"en": ["heart"], "zh": "心"},
    "blood": {"en": ["blood"], "zh": "血"},
    # nature
    "tree": {"en": ["tree"], "zh": "树"},
    "flower": {"en": ["flower"], "zh": "花"},
    "grass": {"en": ["grass"], "zh": "草"},
    "mountain": {"en": ["mountain"], "zh": "山"},
    "river": {"en": ["river"], "zh": "河"},
    "sea": {"en": ["sea", "ocean"], "zh": "海"},
    "sky": {"en": ["sky"], "zh": "天"},
    "sun": {"en": ["sun"], "zh": "日"},
    "moon": {"en": ["moon"], "zh": "月"},
    "star": {"en": ["star"], "zh": "星"},
    "snow": {"en": ["snow"], "zh": "雪"},
    "rain": {"en": ["rain"], "zh": "雨"},
    "wind": {"en": ["wind"], "zh": "风"},
    "cloud": {"en": ["cloud"], "zh": "云"},
    "fire": {"en": ["fire", "flame"], "zh": "火"},
    "stone": {"en": ["stone", "rock"], "zh": "石"},
    "forest": {"en": ["forest", "wood"], "zh": "林"},
    "lake": {"en": ["lake"], "zh": "湖"},
    # places / buildings
    "house": {"en": ["house", "home"], "zh": "房子"},
    "school": {"en": ["school"], "zh": "学校"},
    "hospital": {"en": ["hospital"], "zh": "医院"},
    "shop": {"en": ["shop", "store"], "zh": "商店"},
    "restaurant": {"en": ["restaurant"], "zh": "饭馆"},
    "station": {"en": ["station"], "zh": "车站"},
    "bank": {"en": ["bank"], "zh": "银行"},
    "library": {"en": ["library"], "zh": "图书馆"},
    "park": {"en": ["park"], "zh": "公园"},
    "office": {"en": ["office"], "zh": "办公室"},
    "room": {"en": ["room"], "zh": "房间"},
    "kitchen": {"en": ["kitchen"], "zh": "厨房"},
    "door": {"en": ["door"], "zh": "门"},
    "window": {"en": ["window"], "zh": "窗"},
    "bed": {"en": ["bed"], "zh": "床"},
    "table": {"en": ["table"], "zh": "桌子"},
    "chair": {"en": ["chair"], "zh": "椅子"},
    "lamp": {"en": ["lamp", "light"], "zh": "灯"},
    # transport
    "car": {"en": ["car", "automobile"], "zh": "汽车"},
    "bus": {"en": ["bus"], "zh": "公共汽车"},
    "train": {"en": ["train"], "zh": "火车"},
    "airplane": {"en": ["airplane", "aeroplane", "plane"], "zh": "飞机"},
    "ship": {"en": ["ship"], "zh": "船"},
    "bicycle": {"en": ["bicycle", "bike"], "zh": "自行车"},
    "motorcycle": {"en": ["motorcycle"], "zh": "摩托车"},
    "truck": {"en": ["truck", "lorry"], "zh": "卡车"},
    # objects
    "book": {"en": ["book"], "zh": "书"},
    "pen": {"en": ["pen"], "zh": "笔"},
    "paper": {"en": ["paper"], "zh": "纸"},
    "bag": {"en": ["bag"], "zh": "包"},
    "phone": {"en": ["phone", "telephone"], "zh": "电话"},
    "computer": {"en": ["computer"], "zh": "电脑"},
    "money": {"en": ["money"], "zh": "钱"},
    "card": {"en": ["card"], "zh": "卡"},
    "umbrella": {"en": ["umbrella"], "zh": "伞"},
    "clock": {"en": ["clock"], "zh": "钟"},
    "watch": {"en": ["watch"], "zh": "表"},
    "glasses": {"en": ["glasses", "spectacles"], "zh": "眼镜"},
    "hat": {"en": ["hat"], "zh": "帽子"},
    "shoe": {"en": ["shoe"], "zh": "鞋"},
    "shirt": {"en": ["shirt"], "zh": "衬衫"},
    "coat": {"en": ["coat"], "zh": "外套"},
    # people
    "teacher": {"en": ["teacher"], "zh": "老师"},
    "doctor": {"en": ["doctor", "physician"], "zh": "医生"},
    "student": {"en": ["student", "pupil"], "zh": "学生"},
    "police": {"en": ["police", "policeman"], "zh": "警察"},
    "farmer": {"en": ["farmer"], "zh": "农民"},
    "baby": {"en": ["baby", "infant"], "zh": "婴儿"},
    "child": {"en": ["child"], "zh": "孩子"},
    # actions a still photo can suggest
    "run": {"en": ["run"], "zh": "跑"},
    "walk": {"en": ["walk"], "zh": "走"},
    "swim": {"en": ["swim"], "zh": "游泳"},
    "read": {"en": ["read"], "zh": "读"},
    "eat": {"en": ["eat"], "zh": "吃"},
    "drink": {"en": ["drink"], "zh": "喝"},
    "sleep": {"en": ["sleep"], "zh": "睡"},
    "sit": {"en": ["sit"], "zh": "坐"},
    "stand": {"en": ["stand"], "zh": "站"},
    "jump": {"en": ["jump"], "zh": "跳"},
    "write": {"en": ["write"], "zh": "写"},
    "cook": {"en": ["cook"], "zh": "做饭"},
    "drive": {"en": ["drive"], "zh": "开车"},
    "fly": {"en": ["fly"], "zh": "飞"},
    "cry": {"en": ["cry", "weep"], "zh": "哭"},
    "laugh": {"en": ["laugh", "smile"], "zh": "笑"},
}

POS_PREFIX = re.compile(r"^[a-z]{1,5}\.\s*")
SPLIT = re.compile(r"[;,/]")


def normalise_gloss(gloss: str) -> list[str]:
    """First gloss segment, lowercased, POS prefix dropped, parentheses removed."""
    if not gloss:
        return []
    parts = []
    for chunk in SPLIT.split(gloss):
        chunk = POS_PREFIX.sub("", chunk.strip()).strip()
        chunk = re.sub(r"\(.*?\)", "", chunk).strip(" .")
        if chunk:
            parts.append(chunk.lower())
    return parts


def build_keyword_index() -> list[tuple[str, str]]:
    """(keyword, concept) pairs, longest keyword first so 'police' wins over 'car'."""
    pairs: list[tuple[str, str]] = []
    for concept, spec in LEXICON.items():
        for kw in spec["en"]:  # type: ignore[index]
            pairs.append((kw, concept))
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "build" / "dictionary.sqlite"))
    ap.add_argument("--top", type=int, default=3000)
    ap.add_argument("--out-dir", default=str(ROOT / "review"))
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT e.entry_id, e.simplified, e.freq_rank, "
        "(SELECT s.gloss_en FROM senses s WHERE s.entry_id = e.entry_id "
        " ORDER BY s.sense_order LIMIT 1) AS gloss_en "
        "FROM entries e WHERE e.is_proper = 0 AND e.freq_rank IS NOT NULL "
        "ORDER BY e.freq_rank LIMIT ?",
        (args.top,),
    ).fetchall()
    taken = {
        r["entry_id"]
        for r in con.execute("SELECT DISTINCT entry_id FROM entry_images").fetchall()
    }
    con.close()

    keywords = build_keyword_index()
    zh_index = {
        str(spec["zh"]): concept for concept, spec in LEXICON.items() if spec.get("zh")
    }

    per_concept: dict[str, list[sqlite3.Row]] = {c: [] for c in LEXICON}
    unmapped: list[tuple[sqlite3.Row, str]] = []
    for row in rows:
        if row["entry_id"] in taken:
            continue
        concept = ""
        headword = row["simplified"] or ""
        if headword in zh_index:
            concept = zh_index[headword]
        else:
            gloss_parts = normalise_gloss(row["gloss_en"] or "")
            for part in gloss_parts:
                for kw, cand in keywords:
                    if re.search(rf"\b{re.escape(kw)}\b", part):
                        concept = cand
                        break
                if concept:
                    break
        if concept:
            per_concept[concept].append(row)
        else:
            unmapped.append((row, (row["gloss_en"] or "").strip()))

    covered = sum(len(v) for v in per_concept.values())
    single_char_or_gloss = covered

    concept_rows = []
    for concept, members in per_concept.items():
        if not members:
            continue
        concept_rows.append(
            {
                "concept": concept,
                "entries_covered": len(members),
                "share_of_top_n_pct": round(100.0 * len(members) / max(1, len(rows)), 2),
                "keywords": "|".join(LEXICON[concept]["en"]),
                "zh_seed": LEXICON[concept].get("zh", ""),
                "sample_words": " ".join(m["simplified"] for m in members[:8]),
                "best_rank": min(int(m["freq_rank"]) for m in members),
            }
        )
    concept_rows.sort(key=lambda r: -r["entries_covered"])

    concepts_csv = out_dir / "image_concepts.csv"
    with concepts_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(concept_rows[0].keys()))
        writer.writeheader()
        writer.writerows(concept_rows)

    unmapped_csv = out_dir / "image_concepts_unmapped.csv"
    with unmapped_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["freq_rank", "simplified", "gloss_en"])
        for row, gloss in unmapped:
            writer.writerow([row["freq_rank"], row["simplified"], gloss])

    print(f"candidate entries in top {args.top} (no picture yet): {len(rows):,}")
    print(f"with a visual concept: {covered:,}  ({100.0*covered/max(1,len(rows)):.1f}%)")
    print(f"without one (abstract/functional): {len(unmapped):,}")
    print(f"concepts that would fire: {len(concept_rows)} of {len(LEXICON)} in the lexicon")
    print()
    print(f"{'concept':<12}{'entries':>8}{'share':>8}  sample")
    for r in concept_rows[:20]:
        print(f"{r['concept']:<12}{r['entries_covered']:>8}{r['share_of_top_n_pct']:>7}%  {r['sample_words'][:48]}")
    print()
    print(f"wrote {concepts_csv}")
    print(f"wrote {unmapped_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
