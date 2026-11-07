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

import sqlite3
from functools import lru_cache
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


def _row_to_entry(con: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    senses = con.execute(
        "SELECT sense_id, sense_order, gloss_en, gloss_zh, gloss_ne, ne_status "
        "FROM senses WHERE entry_id = ? ORDER BY sense_order",
        (row["entry_id"],),
    ).fetchall()

    sense_list = []
    for sense in senses:
        gloss = sense["gloss_en"] or ""
        sense_list.append(
            {
                "sense_id": f"zh{row['entry_id']}:{sense['sense_order']}",
                "word_en": _short_gloss(gloss),
                "word_zh": row["simplified"],
                "pinyin": row["pinyin_marked"],
                "ipa_en": "",
                "part_of_speech": "",
                "meaning_en": gloss,
                # Empty until the Kaikki import / Nepali run land; the client
                # renders these blocks as "pending", never as translations.
                "meaning_zh": sense["gloss_zh"] or "",
                "meaning_ne": sense["gloss_ne"] or "",
                "meaning_ne_status": (
                    "published" if sense["ne_status"] == "reviewed" else "pending"
                ),
                "examples": [],
            }
        )

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
        # because "to arrange" is longer. Score candidates instead: lead articles
        # and "to"/"a"/"the" are stripped, an exact gloss beats a prefix, a whole
        # word beats a substring, and HSK5 words (the ones learners actually
        # meet) get a bonus.
        row = con.execute(
            "SELECT e.*, s.gloss_en, "
            " CASE WHEN LOWER(TRIM(s.gloss_en)) IN (?, ?, ?, ?) THEN 3 "
            "      WHEN LOWER(s.gloss_en) LIKE ? || ' %' OR LOWER(s.gloss_en) "
            "           LIKE 'to ' || ? || '%' OR LOWER(s.gloss_en) LIKE ? || ',%' "
            "        THEN 2 "
            "      WHEN LOWER(s.gloss_en) LIKE '% ' || ? || ' %' OR LOWER(s.gloss_en) "
            "           LIKE '% ' || ? THEN 1 "
            "      ELSE 0 END AS match_score "
            "FROM senses s JOIN entries e ON e.entry_id = s.entry_id "
            "WHERE LOWER(s.gloss_en) LIKE '%' || ? || '%' AND e.is_proper = 0 "
            "ORDER BY match_score DESC, s.sense_order, "
            "         (e.hsk_level IS NOT NULL) DESC, "
            "         LENGTH(s.gloss_en), e.entry_id "
            "LIMIT 1",
            (q_lower, "to " + q_lower, "a " + q_lower, "the " + q_lower,
             q_lower, q_lower, q_lower, q_lower, q_lower, q_lower),
        ).fetchone()
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
