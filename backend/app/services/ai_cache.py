"""Persistent cache for AI-generated entries ("never request twice").

AI answers cost money and take 3–10 s, so every successful generation is stored
so a repeated lookup of the same word in the same direction is a single indexed
read (~0.5 ms) instead of an API call, and the answer stays available when a
provider is rate-limited.

The cache lives in its OWN SQLite file (``settings.ai_cache_path``), never in
``dictionary.sqlite``. That file is a pinned, shipped asset whose fingerprint is
checked by tests/test_execution_guards.py; a live request writing into it made
the guard fail with a hash that changed on every AI lookup. Runtime data must
not share a file with a shipped artifact.

Nothing here is trusted as dictionary truth: cached rows keep
`status = 'ai_generated'` and the API flags them `source="ai"`, `unverified=true`.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from app.core.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_cache (
  query      TEXT NOT NULL,
  lang       TEXT NOT NULL,
  payload    TEXT NOT NULL,
  provider   TEXT NOT NULL DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'ai_generated',
  created_at INTEGER NOT NULL,
  hits       INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (query, lang)
);
"""


def _path() -> Path:
    """Resolve the runtime cache file, anchored to `backend/`, never to the cwd.

    `settings.ai_cache_path` is relative by default; resolving it against the
    process working directory means launching uvicorn from anywhere else creates
    a stray database next to that folder, so a second copy of the cache silently
    appears and the "never request twice" guarantee is lost.
    """
    p = Path(settings.ai_cache_path)
    if p.is_absolute():
        return p
    return Path(__file__).resolve().parents[2] / p


def _connect_rw() -> sqlite3.Connection:
    """Open the cache file read-write, creating it (and its table) if needed.

    The directory is created so the cache also works on a machine that has not
    built the dictionary yet (cache-only database).
    """
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(SCHEMA)
    return con


def get(query: str, lang: str) -> dict | None:
    con = _connect_rw()
    try:
        row = con.execute(
            "SELECT payload FROM ai_cache WHERE query = ? AND lang = ?",
            (query.strip().lower(), lang),
        ).fetchone()
        if row is None:
            return None
        con.execute(
            "UPDATE ai_cache SET hits = hits + 1 WHERE query = ? AND lang = ?",
            (query.strip().lower(), lang),
        )
        con.commit()
        return json.loads(row[0])
    except (sqlite3.Error, json.JSONDecodeError):
        return None
    finally:
        con.close()


def put(query: str, lang: str, payload: dict, provider: str = "") -> bool:
    con = _connect_rw()
    if con is None:
        return False
    q = query.strip().lower()
    try:
        previous = con.execute(
            "SELECT hits FROM ai_cache WHERE query = ? AND lang = ?", (q, lang)
        ).fetchone()
        hits = previous[0] if previous else 0
        con.execute(
            "INSERT OR REPLACE INTO ai_cache(query, lang, payload, provider, "
            "status, created_at, hits) VALUES (?,?,?,?,?,?,?)",
            (q, lang, json.dumps(payload, ensure_ascii=False), provider,
             "ai_generated", int(time.time()), hits),
        )
        con.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        con.close()


def stats() -> dict:
    con = _connect_rw()
    if con is None:
        return {"rows": 0}
    try:
        rows = con.execute("SELECT COUNT(*), SUM(hits) FROM ai_cache").fetchone()
        return {"rows": rows[0] or 0, "hits": rows[1] or 0}
    finally:
        con.close()
