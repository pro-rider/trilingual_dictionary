"""Keep the two FTS5 indexes inside dictionary.sqlite in step with ``entries``.

Both indexes are derived data, and a tool that appends an entry without updating
both of them leaves the search index quietly short. That is exactly how
``fts_zh`` ended up 76 entries behind (the HSK-5 and exam-word importers wrote
``fts`` only). This module is the one place index rows are written, and
``assert_consistent`` is the check every import path runs at the end.
"""
from __future__ import annotations


class FtsInconsistent(RuntimeError):
    """The indexes no longer mirror ``entries``."""


FTS_COLUMNS = ("simplified", "traditional", "pinyin_search", "english", "category", "entry_id")
FTS_ZH_COLUMNS = ("simplified", "traditional", "english", "entry_id")


def has_trigram(con):
    return con.execute(
        "select count(*) from sqlite_master where type='table' and name='fts_zh'"
    ).fetchone()[0] > 0


def insert_entry(con, *, simplified, traditional, pinyin_search, english, category, entry_id):
    """Insert one entry into both indexes (``fts_zh`` only when it exists)."""
    con.execute(
        "insert into fts(%s) values(?,?,?,?,?,?)" % ", ".join(FTS_COLUMNS),
        (simplified, traditional, pinyin_search, english, category, entry_id),
    )
    if has_trigram(con):
        con.execute(
            "insert into fts_zh(%s) values(?,?,?,?)" % ", ".join(FTS_ZH_COLUMNS),
            (simplified, traditional, english, entry_id),
        )


def counts(con):
    entries = con.execute("select count(*) from entries").fetchone()[0]
    fts = con.execute("select count(*) from fts").fetchone()[0]
    zh = con.execute("select count(*) from fts_zh").fetchone()[0] if has_trigram(con) else None
    return {"entries": entries, "fts": fts, "fts_zh": zh}


def assert_consistent(con):
    """Fail loudly instead of shipping an index that is short by a few rows."""
    c = counts(con)
    problems = []
    if c["fts"] != c["entries"]:
        problems.append("fts has %d rows, entries has %d" % (c["fts"], c["entries"]))
    if c["fts_zh"] is not None and c["fts_zh"] != c["entries"]:
        problems.append("fts_zh has %d rows, entries has %d" % (c["fts_zh"], c["entries"]))
    if problems:
        raise FtsInconsistent("; ".join(problems) + " — rebuild with tools/rebuild_fts.py")
    return c
