"""Build the offline/trilingual SQLite dictionary from CC-CEDICT.

Why this exists
---------------
The app shipped with a 6-entry JSON fixture. Real coverage has to come from open
sources, merged and de-duplicated, in a schema both the Flutter offline layer and
the FastAPI backend can read.

This stage is deliberately limited to one source (CC-CEDICT) so every number it
prints is reproducible and attributable. Later stages add ECDICT (English side),
Kaikki (extra senses), Unihan (character metadata), Tatoeba (examples) through the
`--extra` plug-in slot, using the same merge rules.

Merge / de-duplication rule
---------------------------
An "entry" is a writing form with one reading: (simplified, traditional, pinyin
without tones). Two source lines collapse into one entry when all three agree;
their glosses are appended and exact duplicates dropped. That is what stops the
same word arriving three times from three platforms.

Pinyin is stored three ways because search must work without tone marks:
  pinyin_num     guang1   (source form, tone numbers)
  pinyin_marked  guāng    (display form, diacritics)
  pinyin_plain   guang    (tone-less; ü written v — matches how people type)

Usage
-----
  python tools/build_dictionary.py --cedict data/raw/cedict.txt.gz \
      --out data/build/dictionary.sqlite

Exit code 1 with a readable message if a source is missing or unparsable.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_fts  # noqa: E402  (release gate: exact FTS entry-id coverage)

# --------------------------------------------------------------------------- #
# Pinyin
# --------------------------------------------------------------------------- #

TONE_MARKS = {
    "a": "āáǎà",
    "e": "ēéěè",
    "i": "īíǐì",
    "o": "ōóǒò",
    "u": "ūúǔù",
    "ü": "ǖǘǚǜ",
}


def _syllable_to_marks(syllable: str, tone: int) -> str:
    """guang1 -> guāng; nu:3 -> nǚ. Tone 0/5 means neutral (no mark)."""
    s = syllable.replace("u:", "ü").replace("v", "ü")
    if tone in (0, 5) or not s:
        return s

    # Where the mark goes: a > e > o in "ou" > last vowel.
    index = -1
    if "a" in s:
        index = s.index("a")
    elif "e" in s:
        index = s.index("e")
    elif "ou" in s:
        index = s.index("o")
    else:
        for i, ch in enumerate(s):
            if ch in TONE_MARKS:
                index = i
    if index < 0:
        return s

    ch = s[index]
    table = TONE_MARKS.get(ch)
    if table is None:
        return s
    marked = table[tone - 1]
    return s[:index] + marked + s[index + 1:]


def _plain(syllable: str) -> str:
    """Tone-less, ü written v: lü4 -> lv."""
    return syllable.replace("u:", "v").replace("ü", "v").lower()


def split_pinyin(pinyin_num: str) -> list[tuple[str, int]]:
    """Split a CC-CEDICT reading into (syllable, tone) pieces."""
    pieces: list[tuple[str, int]] = []
    for token in pinyin_num.split():
        m = re.match(r"^([a-zA-Z:]+)([0-5])?$", token)
        if not m:
            continue
        pieces.append((m.group(1).lower(), int(m.group(2) or 5)))
    return pieces


def pinyin_forms(pinyin_num: str) -> tuple[str, str, str]:
    """Return (numeric, marked, plain)."""
    pieces = split_pinyin(pinyin_num)
    if not pieces:
        return pinyin_num, "", ""
    marked = " ".join(_syllable_to_marks(s, t) for s, t in pieces)
    plain = " ".join(_plain(s) for s, t in pieces)
    return pinyin_num, marked, plain


def pinyin_search_variants(plain: str) -> str:
    """Everything a learner might type, for the FTS column."""
    if not plain:
        return ""
    spaced = plain
    joined = plain.replace(" ", "")
    u_form = plain.replace("v", "u")
    return " ".join({spaced, joined, u_form, u_form.replace(" ", "")})


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #

# The requested coverage taxonomy. Keyword match on the English gloss decides the
# bucket; ties resolve by CATEGORY_PRIORITY (first hit wins, so specific beats
# generic). Anything unmatched stays "general" and is never hidden.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "nature": (
        "animal", "bird", "fish", "insect", "mammal", "reptile", "amphibian",
        "plant", "flower", "tree", "leaf", "fruit", "vegetable", "herb", "crop",
        "seed", "root", "bark", "bacteria", "virus", "fungus", "parasite",
        "organ", "cell", "bone", "blood", "mammary", "species", "breed",
    ),
    "science_medicine": (
        "physics", "chemistry", "biology", "astronomy", "disease", "infection",
        "symptom", "medicine", "drug", "surgery", "gene", "dna", "laboratory",
        "microscope", "molecule", "atom", "protein", "enzyme", "vaccine",
        "diagnosis", "therapy", "anatomy", "hormone",
    ),
    "transport": (
        "car", "bus", "truck", "bicycle", "motorcycle", "train", "railway",
        "aircraft", "airplane", "helicopter", "ship", "boat", "vessel", "engine",
        "fuel", "petrol", "diesel", "road", "traffic", "airport", "station",
        "pilot", "driver", "vehicle", "tyre", "tire", "brake",
    ),
    "tools_instruments": (
        "tool", "hammer", "screwdriver", "wrench", "drill", "saw", "pump",
        "instrument", "guitar", "piano", "violin", "drum", "flute", "trumpet",
        "machine", "machinery", "equipment", "device", "meter", "ruler",
    ),
    "technology": (
        "computer", "software", "hardware", "program", "algorithm", "database",
        "network", "internet", "server", "cloud", "robot", "artificial",
        "machine learning", "electronic", "chip", "semiconductor", "app",
        "application", "website", "browser", "encryption", "cyber",
        "smartphone", "telephone", "television", "camera", "battery",
    ),
    "people_society": (
        "family", "father", "mother", "son", "daughter", "wife", "husband",
        "teacher", "student", "school", "university", "college", "education",
        "government", "law", "court", "judge", "police", "army", "soldier",
        "election", "politics", "economy", "culture", "tradition", "festival",
        "religion", "god", "temple", "sport", "game", "team", "music", "dance",
    ),
    "everyday": (
        "food", "drink", "rice", "noodle", "meat", "tea", "wine", "cook",
        "kitchen", "clothes", "clothing", "shoe", "hat", "trousers", "shirt",
        "furniture", "chair", "table", "bed", "house", "room", "building",
        "city", "street", "color", "colour", "number", "time", "hour", "minute",
        "money", "price", "shop",
    ),
    "geography_environment": (
        "mountain", "river", "sea", "ocean", "lake", "desert", "island",
        "weather", "rain", "snow", "wind", "storm", "climate", "earthquake",
        "flood", "drought", "mineral", "metal", "gold", "silver", "iron",
        "coal", "oil", "gas", "energy", "environment", "pollution", "forest",
        "country", "continent", "province", "capital",
    ),
    "language": (
        "verb", "noun", "adjective", "adverb", "pronoun", "conjunction",
        "preposition", "particle", "interjection", "idiom", "phrase",
        "collocation", "synonym", "antonym", "slang", "grammar", "character",
        "word", "sentence", "language", "pronunciation", "dialect", "tone",
    ),
    "business": (
        "bank", "finance", "financial", "accounting", "account", "trade",
        "business", "company", "firm", "tax", "logistics", "customs", "market",
        "management", "manager", "marketing", "contract", "investment",
        "stock", "share", "profit", "loan", "insurance", "agriculture",
        "construction", "engineering", "factory", "industry",
    ),
}

CATEGORY_PRIORITY = (
    "technology", "science_medicine", "transport", "tools_instruments",
    "business", "geography_environment", "nature", "people_society",
    "everyday", "language",
)

# Common measure words, so the classifier flag is data, not a guess.
CLASSIFIERS = {
    "个", "只", "本", "张", "条", "位", "份", "件", "台", "辆", "匹", "头",
    "棵", "朵", "枝", "根", "把", "支", "块", "片", "滴", "壶", "杯", "碗",
    "双", "对", "群", "堆", "串", "束", "副", "套", "层", "座", "间", "家",
    "所", "场", "次", "遍", "趟", "顿", "声", "口", "眼", "步", "页", "篇",
    "首", "曲", "幅", "盘", "袋", "箱", "桶", "包", "粒", "颗", "阵", "番",
}

# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

LINE_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]+)\]\s+/(.*)/\s*$")


@dataclass
class Entry:
    simplified: str
    traditional: str
    pinyin_num: str
    pinyin_marked: str = ""
    pinyin_plain: str = ""
    glosses: list[str] = field(default_factory=list)
    classifiers: list[str] = field(default_factory=list)
    source: str = "CC-CEDICT"

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.simplified, self.traditional, self.pinyin_plain or self.pinyin_num)


def read_cedict(path: Path) -> tuple[list[Entry], dict[str, int]]:
    """Parse `traditional simplified [pinyin] /gloss/gloss/` lines."""
    if not path.exists():
        raise FileNotFoundError(f"CC-CEDICT file not found: {path}")

    opener = gzip.open if path.suffix == ".gz" else open
    entries = []
    stats = {"lines": 0, "bad": 0, "comments": 0}
    seen: dict[tuple[str, str, str], Entry] = {}

    with opener(path, "rt", encoding="utf-8", errors="strict") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            if line.startswith("#"):
                stats["comments"] += 1
                continue
            stats["lines"] += 1

            m = LINE_RE.match(line)
            if not m:
                stats["bad"] += 1
                continue

            traditional, simplified, pinyin, gloss_blob = m.groups()
            num, marked, plain = pinyin_forms(pinyin)

            entry = Entry(
                simplified=simplified,
                traditional=traditional,
                pinyin_num=num,
                pinyin_marked=marked,
                pinyin_plain=plain,
            )

            for gloss in gloss_blob.split("/"):
                gloss = gloss.strip()
                if not gloss:
                    continue
                if gloss.startswith("CL:"):
                    # CL:個|个[ge4] — "traditional|simplified". Comma separates
                    # several classifiers. Store only the simplified form: keeping
                    # both made every such row appear twice in entry_classifiers
                    # (373 duplicated rows in the v2 build).
                    cl = gloss[3:].split("[")[0]
                    for group in cl.split(","):
                        variants = [p.strip() for p in group.split("|") if p.strip()]
                        if variants:
                            entry.classifiers.append(variants[-1])
                    continue
                entry.glosses.append(gloss)

            if not entry.glosses and not entry.classifiers:
                stats["bad"] += 1
                continue

            existing = seen.get(entry.key)
            if existing is None:
                seen[entry.key] = entry
                entries.append(entry)
            else:
                existing.glosses.extend(entry.glosses)
                existing.classifiers.extend(entry.classifiers)

    return entries, stats


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def classify(entry: Entry) -> tuple[str, dict[str, int]]:
    """Pick one category plus the boolean flags the app filters on."""
    text = " ".join(entry.glosses).lower()
    category = "general"
    for name in CATEGORY_PRIORITY:
        if any(k in text for k in CATEGORY_KEYWORDS[name]):
            category = name
            break

    flags = {"is_proper": 0, "is_chengyu": 0, "is_classifier": 0}
    if entry.simplified in CLASSIFIERS:
        flags["is_classifier"] = 1
    if len(entry.simplified) == 4 and ("idiom" in text or "lit." in text):
        flags["is_chengyu"] = 1
    if any(
        marker in text
        for marker in ("surname ", "name of a person", "given name", "abbr. for")
    ):
        flags["is_proper"] = 1
    elif entry.glosses and all(g[:1].isupper() for g in entry.glosses):
        # "Beijing" / "Confucius" — a capitalised-only gloss is a name.
        flags["is_proper"] = 1
    return category, flags


# --------------------------------------------------------------------------- #
# SQLite build
# --------------------------------------------------------------------------- #

SCHEMA = """
PRAGMA journal_mode = OFF;
PRAGMA synchronous = OFF;

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE sources (
  source_id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  url TEXT,
  license TEXT,
  version TEXT,
  downloaded_at TEXT
);

CREATE TABLE entries (
  entry_id INTEGER PRIMARY KEY,
  simplified TEXT NOT NULL,
  traditional TEXT NOT NULL,
  pinyin_num TEXT NOT NULL DEFAULT '',
  pinyin_marked TEXT NOT NULL DEFAULT '',
  pinyin_plain TEXT NOT NULL DEFAULT '',
  pinyin_search TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT 'general',
  pos_primary TEXT NOT NULL DEFAULT '',
  is_proper INTEGER NOT NULL DEFAULT 0,
  is_chengyu INTEGER NOT NULL DEFAULT 0,
  is_classifier INTEGER NOT NULL DEFAULT 0,
  rarity INTEGER,
  freq_rank INTEGER,
  hsk_level INTEGER,
  status TEXT NOT NULL DEFAULT 'imported'   -- imported|ai_translated|reviewed|user_added
);

CREATE TABLE senses (
  sense_id INTEGER PRIMARY KEY,
  entry_id INTEGER NOT NULL REFERENCES entries(entry_id),
  sense_order INTEGER NOT NULL DEFAULT 0,
  gloss_en TEXT NOT NULL,
  gloss_zh TEXT,
  gloss_ne TEXT,
  ne_status TEXT NOT NULL DEFAULT 'none',   -- none|ai_translated|reviewed
  source_id INTEGER REFERENCES sources(source_id)
);

CREATE TABLE examples (
  example_id INTEGER PRIMARY KEY,
  sense_id INTEGER NOT NULL REFERENCES senses(sense_id),
  en TEXT, zh TEXT, ne TEXT,
  source_id INTEGER REFERENCES sources(source_id),
  review_status TEXT NOT NULL DEFAULT 'imported'
);

CREATE TABLE entry_classifiers (
  entry_id INTEGER NOT NULL REFERENCES entries(entry_id),
  classifier TEXT NOT NULL
);

CREATE TABLE characters (
  char TEXT PRIMARY KEY,
  radical TEXT, strokes INTEGER, pinyin TEXT, definition_en TEXT
);

CREATE INDEX idx_entries_simplified ON entries(simplified);
CREATE INDEX idx_entries_traditional ON entries(traditional);
CREATE INDEX idx_entries_pinyin ON entries(pinyin_plain);
CREATE INDEX idx_entries_category ON entries(category);
CREATE INDEX idx_senses_entry ON senses(entry_id);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE fts USING fts5(
  simplified, traditional, pinyin_search, english, category,
  entry_id UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 2'
);
"""

#: An entry's searchable English text: its glosses, in sense order. Both indexes
#: use this one expression so they cannot drift apart.
_ENTRY_ENGLISH = (
    "(select group_concat(gloss_en, ' ') from (select gloss_en from senses "
    "where senses.entry_id = entries.entry_id order by sense_order))"
)


def build(entries: list[Entry], source_meta: dict, out_path: Path) -> dict:
    if out_path.exists():
        out_path.unlink()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(out_path)
    con.executescript(SCHEMA)

    has_trigram = False
    try:
        con.execute(
            "CREATE VIRTUAL TABLE fts_zh USING fts5(simplified, traditional, "
            "english, entry_id UNINDEXED, tokenize = 'trigram')"
        )
        has_trigram = True
    except sqlite3.OperationalError as exc:
        # A missing trigram tokenizer used to be a silent downgrade; it is a
        # release blocker now, because the Chinese index would be empty and the
        # 76-row defect shipped once already.
        con.close()
        raise SystemExit("trigram tokenizer unavailable, refusing to build a "
                         "dictionary without a Chinese index: %s" % exc)

    con.executescript(FTS_SCHEMA)

    con.execute(
        "INSERT INTO sources(name, url, license, version, downloaded_at) "
        "VALUES (?,?,?,?,?)",
        (
            source_meta["name"],
            source_meta["url"],
            source_meta["license"],
            source_meta.get("version", ""),
            source_meta.get("downloaded_at", ""),
        ),
    )
    source_id = 1

    category_counts: dict[str, int] = {}
    flags_total = {"is_proper": 0, "is_chengyu": 0, "is_classifier": 0}
    sense_count = 0

    for entry in entries:
        category, flags = classify(entry)
        category_counts[category] = category_counts.get(category, 0) + 1
        for k, v in flags.items():
            flags_total[k] += v

        cur = con.execute(
            "INSERT INTO entries(simplified, traditional, pinyin_num, pinyin_marked,"
            " pinyin_plain, pinyin_search, category, is_proper, is_chengyu,"
            " is_classifier, status) VALUES (?,?,?,?,?,?,?,?,?,?,'imported')",
            (
                entry.simplified,
                entry.traditional,
                entry.pinyin_num,
                entry.pinyin_marked,
                entry.pinyin_plain,
                pinyin_search_variants(entry.pinyin_plain),
                category,
                flags["is_proper"],
                flags["is_chengyu"],
                flags["is_classifier"],
            ),
        )
        entry_id = cur.lastrowid

        glosses = []
        seen_gloss = set()
        for gloss in entry.glosses:
            key = gloss.lower()
            if key in seen_gloss:
                continue
            seen_gloss.add(key)
            glosses.append(gloss)

        for order, gloss in enumerate(glosses):
            con.execute(
                "INSERT INTO senses(entry_id, sense_order, gloss_en, source_id) "
                "VALUES (?,?,?,?)",
                (entry_id, order, gloss, source_id),
            )
            sense_count += 1

        for cl in dict.fromkeys(entry.classifiers):
            con.execute(
                "INSERT INTO entry_classifiers(entry_id, classifier) VALUES (?,?)",
                (entry_id, cl),
            )

    # FTS is generated once, last, from the finished tables — never row by row
    # inside the import loop. That ordering is what keeps an index from falling
    # short of `entries` when a later step adds or reshapes rows.
    con.execute("DELETE FROM fts")
    con.execute(
        "INSERT INTO fts(simplified, traditional, pinyin_search, english, category, entry_id) "
        "SELECT simplified, traditional, pinyin_search, %s, category, entry_id FROM entries"
        % _ENTRY_ENGLISH)
    con.execute("DELETE FROM fts_zh")
    con.execute(
        "INSERT INTO fts_zh(simplified, traditional, english, entry_id) "
        "SELECT simplified, traditional, %s, entry_id FROM entries" % _ENTRY_ENGLISH)

    con.executemany(
        "INSERT INTO meta(key, value) VALUES (?,?)",
        [
            ("dataset_version", "2"),
            ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
            ("builder", "tools/build_dictionary.py"),
            ("source_primary", source_meta["name"]),
            ("has_trigram_fts", "1" if has_trigram else "0"),
        ],
    )

    con.commit()
    con.execute("VACUUM")
    con.commit()

    counts = {
        "entries": con.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        "senses": con.execute("SELECT COUNT(*) FROM senses").fetchone()[0],
        "classifier_rows": con.execute(
            "SELECT COUNT(*) FROM entry_classifiers"
        ).fetchone()[0],
        "fts_rows": con.execute("SELECT COUNT(*) FROM fts").fetchone()[0],
        "unique_simplified": con.execute(
            "SELECT COUNT(DISTINCT simplified) FROM entries"
        ).fetchone()[0],
        "unique_traditional": con.execute(
            "SELECT COUNT(DISTINCT traditional) FROM entries"
        ).fetchone()[0],
        "unique_pinyin_plain": con.execute(
            "SELECT COUNT(DISTINCT pinyin_plain) FROM entries"
        ).fetchone()[0],
        "duplicate_keys": con.execute(
            "SELECT COUNT(*) FROM (SELECT simplified, traditional, pinyin_plain, "
            "COUNT(*) c FROM entries GROUP BY 1,2,3 HAVING c > 1)"
        ).fetchone()[0],
        "empty_gloss_senses": con.execute(
            "SELECT COUNT(*) FROM senses WHERE TRIM(gloss_en) = ''"
        ).fetchone()[0],
        "senses_per_entry": round(
            con.execute("SELECT COUNT(*) FROM senses").fetchone()[0]
            / max(con.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 1),
            2,
        ),
    }

    con.execute("PRAGMA optimize")
    con.commit()
    con.close()

    return {
        "counts": counts,
        "categories": dict(sorted(category_counts.items(), key=lambda kv: -kv[1])),
        "flags": flags_total,
        "size_bytes": out_path.stat().st_size,
        "trigram_fts": has_trigram,
        "sense_count": sense_count,
    }


def sample_queries(db: Path) -> dict:
    """Prove the DB answers the four lookup shapes the app needs."""
    con = sqlite3.connect(db)
    out = {}

    def timed(label: str, sql: str, params: tuple) -> None:
        t0 = time.perf_counter()
        rows = con.execute(sql, params).fetchmany(5)
        out[label] = {
            "ms": round((time.perf_counter() - t0) * 1000, 2),
            "rows": [
                {"zh": r[0], "trad": r[1], "pinyin": r[2], "gloss": (r[3] or "")[:70]}
                for r in rows
            ],
        }

    timed(
        "exact_zh",
        "SELECT simplified, traditional, pinyin_marked, "
        "(SELECT gloss_en FROM senses WHERE entry_id = e.entry_id LIMIT 1) "
        "FROM entries e WHERE simplified = ? LIMIT 5",
        ("光",),
    )
    timed(
        "pinyin_no_tones",
        "SELECT e.simplified, e.traditional, e.pinyin_marked, "
        "(SELECT gloss_en FROM senses WHERE entry_id = e.entry_id LIMIT 1) "
        "FROM entries e WHERE e.pinyin_plain = ? LIMIT 5",
        ("ni hao",),
    )
    timed(
        "prefix_autocomplete",
        "SELECT e.simplified, e.traditional, e.pinyin_marked, "
        "(SELECT gloss_en FROM senses WHERE entry_id = e.entry_id LIMIT 1) "
        "FROM entries e WHERE e.pinyin_plain LIKE ? || '%' LIMIT 5",
        ("guang",),
    )
    timed(
        "fts_english",
        "SELECT e.simplified, e.traditional, e.pinyin_marked, "
        "(SELECT gloss_en FROM senses WHERE entry_id = e.entry_id LIMIT 1) "
        "FROM fts JOIN entries e ON e.entry_id = fts.entry_id "
        "WHERE fts MATCH ? LIMIT 5",
        ('english: "light"',),
    )
    con.close()
    return out


def nepali_cost_estimate(db: Path) -> dict:
    """Token maths for the Prompt-4 translation run, measured on the built DB.

    One sense is sent with: Chinese word, pinyin, part of speech, the English
    gloss, and (when present) one example — about 25 tokens of context — plus the
    gloss itself (~1.35 tokens per English word). Devanagari output runs longer
    than the English source, so output is estimated at 1.6x the source words.
    """
    con = sqlite3.connect(db)
    rows = con.execute("SELECT gloss_en FROM senses").fetchall()
    con.close()

    glosses = [r[0] or "" for r in rows]
    words = sum(len(g.split()) for g in glosses)
    context_overhead = 25 * len(glosses)

    input_tokens = int(context_overhead + words * 1.35)
    output_tokens = int(words * 1.6)

    return {
        "senses_to_translate": len(glosses),
        "gloss_words": words,
        "est_input_tokens": input_tokens,
        "est_output_tokens": output_tokens,
        # Batch of 20 senses per request keeps the context overhead amortised.
        "est_requests_at_batch20": -(-len(glosses) // 20),
        "usd_cheap_model": round(
            (input_tokens * 0.30 + output_tokens * 0.60) / 1_000_000, 2
        ),
        "usd_gpt_class": round(
            (input_tokens * 2.50 + output_tokens * 10.0) / 1_000_000, 2
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cedict", required=True, help="CC-CEDICT .txt or .txt.gz")
    parser.add_argument("--out", default="data/build/dictionary.sqlite")
    parser.add_argument(
        "--source-url",
        default="https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz",
    )
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    entries, parse_stats = read_cedict(Path(args.cedict))
    parse_s = round(time.perf_counter() - t0, 2)
    if not entries:
        print("No entries parsed — check the source file format.", file=sys.stderr)
        return 1

    report = build(
        entries,
        {
            "name": "CC-CEDICT",
            "url": args.source_url,
            "license": "CC BY-SA 4.0",
            "version": "1.0 (mdbg export)",
            "downloaded_at": time.strftime("%Y-%m-%d"),
        },
        Path(args.out),
    )
    report["parse"] = {"seconds": parse_s, **parse_stats}
    report["built_in_seconds"] = round(time.perf_counter() - t0, 1)
    report["db"] = str(Path(args.out).resolve())
    report["size_mb"] = round(report["size_bytes"] / (1024 * 1024), 2)
    report["samples"] = sample_queries(Path(args.out))
    report["nepali_estimate"] = nepali_cost_estimate(Path(args.out))

    # Release gate: the artifact is only usable if both indexes cover every entry
    # id exactly. On failure the artifact is removed — a build must never leave a
    # shippable dictionary behind with a hole in its search index.
    fts = validate_fts.check(args.out)
    report["fts"] = fts
    if not fts["ok"]:
        Path(args.out).unlink(missing_ok=True)
        print("FTS validation failed, artifact discarded: %s" % "; ".join(fts["failures"]),
              file=sys.stderr)
        return 1

    report_path = Path(args.out).with_suffix(".report.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nReport written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
