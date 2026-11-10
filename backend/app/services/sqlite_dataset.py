"""SQLite-backed lookup over the merged dictionary (data/build/dictionary.sqlite).

Why a second backend next to the JSON dataset
---------------------------------------------
`data/seed/en_zh_ne.json` is the curated, reviewed, three-language fixture (6
entries). It stays first in the lookup order because its Chinese and Nepali
meanings are human-written. The SQLite dictionary built by
`tools/build_dictionary.py` supplies raw coverage — 123k entries — for words the
fixture does not have. Rows coming from it carry `ne_status='none'` and empty
Chinese/Nepali meanings until the Kaikki import and the Nepali run fill them,
so the API never pretends a machine gloss is a reviewed translation.

Every query here is read-only and parameterised; no string interpolation.
"""

from __future__ import annotations

import re
import sqlite3
from functools import lru_cache

from app.services.gloss import head_is_disqualified, normalize_gloss
from pathlib import Path
from typing import Any

from app.core.config import settings


def _variants(text: str) -> list[str]:
    """Spellings a learner might type for a pinyin query."""
    base = text.strip().lower().replace("u:", "v")
    out = [base]
    joined = base.replace(" ", "")
    if joined != base:
        out.append(joined)
    u_form = base.replace("v", "u")
    if u_form != base:
        out.append(u_form)
        out.append(u_form.replace(" ", ""))
    return [v for v in dict.fromkeys(out) if v]


def _db_path() -> Path:
    return Path(settings.dictionary_db_path)


@lru_cache(maxsize=1)
def available() -> bool:
    """True when the built database exists and has entries."""
    path = _db_path()
    if not path.exists():
        return False
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            row = con.execute("SELECT COUNT(*) FROM entries").fetchone()
        return bool(row and row[0])
    except sqlite3.Error:
        return False


def reset_cache() -> None:
    """Forget the availability probe (used after a rebuild or in tests)."""
    available.cache_clear()


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _short_gloss(gloss: str) -> str:
    """First readable English gloss: 'light; ray' -> 'light'."""
    head = gloss.split(";")[0].split("(")[0].strip()
    return head or gloss.strip()


_ARTICLES = ("to ", "a ", "an ", "the ")


def _strip_article(piece: str) -> str:
    p = piece.strip().lower()
    for art in _ARTICLES:
        if p.startswith(art):
            return p[len(art):].strip()
    return p


def _english_queries(raw: str) -> list[str]:
    """Typed forms to try: the word itself plus its singular / plural."""
    q = raw.strip().lower()
    out = [q]
    if q.endswith("es") and len(q) > 4:
        out.append(q[:-2])
    if q.endswith("s") and len(q) > 3:
        out.append(q[:-1])
    elif len(q) >= 3:
        out.append(q + "s")
    return [v for v in dict.fromkeys(out) if v]


def _score_tier(score: int) -> int:
    """Collapse the raw score into a band so frequency can decide between
    "the definition IS this word" (100) and "this word is one of the
    definitions" (85). Without this, "behaviors" picks 品行 (glossed exactly
    "behavior") over the word people actually mean, 行为."""
    if score >= 85:
        return 0
    if score >= 75:
        return 1
    if score >= 60:
        return 2
    return 3


def _gloss_score(gloss: str, queries: list[str]) -> int:
    """How well an English gloss defines the typed word.

    A gloss like ``(bird species of China) Nepal fulvetta`` must NOT answer
    "Nepal": the word only appears inside a parenthetical explanation of a
    different headword. So scoring looks at the *definition part* only — but
    the bracket may sit at either end of the gloss, so it is **stripped**
    wherever it is (``gloss.normalize_gloss``) rather than truncated at the
    first "(". Truncating made every ``(computing) database``-style sense score
    zero, and those senses are the only answer for 1,481 query words.

    100  a segment IS the word (after stripping to/a/an/the)
     90  a segment starts with the word ("to arrange", "arrange; plan")
     60  the word ends a segment ("to put ... in order" + "order")
     40  the word appears as a whole word in the definition part
      0  no defensible match -> the caller must return None, never a guess
    """
    if head_is_disqualified(gloss or ""):
        return 0
    text = normalize_gloss(gloss)
    definition = text
    segments = [s for s in re.split(r"[;,/、]", definition) if s.strip()]

    best = 0
    for idx, segment in enumerate(segments):
        piece = _strip_article(segment)
        # The first segment is the head definition; a hit there is worth more
        # than a hit buried among later semicolon alternatives (东土 = "the East;
        # China" must lose to 中国 = "China").
        for q in queries:
            if piece == q:
                return 100 if idx == 0 else 85
            # "middle age" is not a definition of "middle", and "in total
            # there are ..." is not a definition of "in total": a longer
            # phrase that merely starts with the query is only a weak hit.
            if piece.startswith(q + " ") or piece.startswith(q + "'s"):
                best = max(best, 60)
            elif piece.endswith(" " + q):
                best = max(best, 60)
    if best:
        return best

    for q in queries:
        if re.search(rf"(?<![a-z]){re.escape(q)}(?![a-z])", definition):
            return 40
    return 0


def _best_english_row(con: sqlite3.Connection, q_lower: str) -> sqlite3.Row | None:
    """Rank every gloss containing the word, then keep the best one."""
    queries = _english_queries(q_lower)
    candidates: list[sqlite3.Row] = []
    # Every inflected form must be fetched, not just the typed one: the SQL used
    # to filter on "%behaviors%" only, so 行为 ("action; conduct; behavior")
    # never entered the ranking and "behaviors" returned nothing.
    seen: set[int] = set()
    for q in queries:
        # Order by frequency *before* the LIMIT: with an unordered LIMIT the
        # commonest headword (水 for "water") can be cut off entirely, and a
        # rare entry answers instead.
        rows = con.execute(
            "SELECT e.*, s.gloss_en, s.sense_order "
            "FROM senses s JOIN entries e ON e.entry_id = s.entry_id "
            "WHERE LOWER(s.gloss_en) LIKE '%' || ? || '%' "
            "ORDER BY e.freq_rank IS NULL, e.freq_rank, LENGTH(s.gloss_en) "
            "LIMIT 400",
            (q,),
        ).fetchall()
        for row in rows:
            key = (row["entry_id"], row["sense_order"])
            if key in seen:
                continue
            seen.add(key)
            candidates.append(row)

    best: sqlite3.Row | None = None
    best_key: tuple = ()
    for row in candidates:
        score = _gloss_score(row["gloss_en"] or "", queries)
        if score < 40:
            continue
        # Rank the way a learner expects. Score first, but banded so usage can
        # decide between "the definition IS this word" (100) and "this word is
        # one of its definitions" (85). Then how often the word is really used
        # (wordfreq: 水 #653 beats 四大 #4,622; 书 #539 beats 册 #4,264; 行为
        # #476 beats 品行 #35,279). `is_proper` is deliberately NOT used: the
        # build flags a whole entry when any sense is a name (水 carries a
        # surname sense, 书 an abbreviation sense), which made rare entries win.
        #
        # `sense_order` stays: on this corpus it is the only available proxy for
        # "this entry's own primary meaning is this word", which is what a
        # learner wants (行为 sense 0 = behavior, 行 sense 0 = to walk). It was
        # removed in one experiment and three protected tests failed
        # (toy→玩, raisin→提子, behaviors→行), while the benchmark stayed flat
        # at 178/190 — so the signal is real and the loss is not.
        key = (
            _score_tier(score),
            row["sense_order"],
            row["freq_rank"] is None,
            row["freq_rank"] or 0,
            len(row["gloss_en"] or ""),
            len(row["simplified"] or ""),
            row["entry_id"],
        )
        if best is None or key < best_key:
            best, best_key = row, key
    return best


def _row_to_entry(con: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    senses = con.execute(
        "SELECT sense_id, sense_order, gloss_en, gloss_zh, gloss_ne, ne_status "
        "FROM senses WHERE entry_id = ? ORDER BY sense_order",
        (row["entry_id"],),
    ).fetchall()

    sense_list = []
    for sense in senses:
        gloss = sense["gloss_en"] or ""
        # CC-CEDICT ships no Chinese gloss, so the 中文 block would render as an
        # empty pink box on the phone. Fall back to the headword itself — that is
        # what a Chinese reader wants to see there anyway.
        meaning_zh = sense["gloss_zh"] or row["simplified"]
        sense_list.append(
            {
                "sense_id": f"zh{row['entry_id']}:{sense['sense_order']}",
                "word_en": _short_gloss(gloss),
                "word_zh": row["simplified"],
                "pinyin": row["pinyin_marked"],
                "ipa_en": "",
                "part_of_speech": "",
                "meaning_en": gloss,
                "meaning_zh": meaning_zh,
                "meaning_ne": sense["gloss_ne"] or "",
                "meaning_ne_status": (
                    "published" if sense["ne_status"] == "reviewed" else "pending"
                ),
                "examples": [],
            }
        )

    # For an English lookup, show the sense that actually matched first:
    # "apple" used to open on 苹果's sense 0 "Apple (American tech company)".
    matched_order = row["sense_order"] if "sense_order" in row.keys() else None
    if matched_order is not None:
        at = next((i for i, s in enumerate(sense_list)
                   if s["sense_id"].endswith(f":{matched_order}")), -1)
        if at > 0:
            sense_list.insert(0, sense_list.pop(at))

    first = sense_list[0] if sense_list else None
    return {
        "entry_id": f"zh{row['entry_id']}",
        "word_en": first["word_en"] if first else "",
        "word_zh": row["simplified"],
        "senses": sense_list,
        "source": "cc-cedict",
        "category": row["category"],
        "is_proper": bool(row["is_proper"]),
    }


def find_entry(query: str, lang: str) -> dict[str, Any] | None:
    """Exact → prefix → full-text lookup. Returns None when nothing matches."""
    q = (query or "").strip()
    if not q or not available():
        return None
    q_lower = q.lower()

    con = _connect()
    try:
        if lang == "zh":
            row = con.execute(
                "SELECT * FROM entries WHERE simplified = ? "
                "ORDER BY LENGTH(simplified) LIMIT 1",
                (q,),
            ).fetchone()
            if row is None:
                row = con.execute(
                    "SELECT * FROM entries WHERE traditional = ? "
                    "ORDER BY LENGTH(simplified) LIMIT 1",
                    (q,),
                ).fetchone()
            if row is None:
                row = con.execute(
                    "SELECT * FROM entries WHERE simplified LIKE ? || '%' "
                    "ORDER BY LENGTH(simplified) LIMIT 1",
                    (q,),
                ).fetchone()
            if row is not None:
                return _row_to_entry(con, row)

        # Pinyin without tones: "ni hao", "nihao", "nu:3"->"nv".
        plain = _variants(q_lower)
        if plain:
            for candidate in plain[:2]:
                row = con.execute(
                    "SELECT * FROM entries WHERE pinyin_plain = ? "
                    "ORDER BY is_proper, LENGTH(simplified) LIMIT 1",
                    (candidate,),
                ).fetchone()
                if row is not None:
                    return _row_to_entry(con, row)

        # English gloss. A plain "shortest match wins" rule is wrong: "arrange"
        # used to return 布局 ("arrangement") while 安排 ("to arrange") existed,
        # because "to arrange" is longer. Candidates are scored instead (see
        # _gloss_score) and a score of 0 means "no answer", never a guess:
        # searching "Nepal" must return 尼泊尔, not the bird "Nepal fulvetta".
        row = _best_english_row(con, q_lower)
        if row is not None:
            return _row_to_entry(con, row)
    finally:
        con.close()

    return None


def suggest(query: str, lang: str, limit: int = 6) -> list[str]:
    """Prefix suggestions from the whole dictionary (not just the fixture)."""
    q = (query or "").strip()
    if not q or not available():
        return []

    con = _connect()
    try:
        rows = con.execute(
            "SELECT DISTINCT simplified FROM entries "
            "WHERE simplified LIKE ? || '%' AND simplified != ? "
            "ORDER BY LENGTH(simplified) LIMIT ?",
            (q, q, limit),
        ).fetchall()
        if rows:
            return [r[0] for r in rows]

        rows = con.execute(
            "SELECT DISTINCT pinyin_marked FROM entries "
            "WHERE pinyin_plain LIKE ? || '%' AND pinyin_marked != '' "
            "ORDER BY LENGTH(simplified) LIMIT ?",
            (q.lower(), limit),
        ).fetchall()
        return [r[0] for r in rows if r[0]]
    finally:
        con.close()


def stats() -> dict[str, Any]:
    """Cheap counters for /health and the credits screen."""
    if not available():
        return {"available": False}
    con = _connect()
    try:
        entries = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        senses = con.execute("SELECT COUNT(*) FROM senses").fetchone()[0]
        images = (
            con.execute("SELECT COUNT(*) FROM images").fetchone()[0]
            if _has_images_table(con)
            else 0
        )
    finally:
        con.close()
    return {
        "available": True,
        "entries": entries,
        "senses": senses,
        "images": images,
        "path": str(_db_path()),
    }


def _has_images_table(con: sqlite3.Connection) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='images'"
    ).fetchone()
    return bool(row)
