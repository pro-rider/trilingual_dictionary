"""Exact-ID completeness check for the two FTS5 search indexes.

Row counts are not proof: an index can hold the right number of rows and still
miss a word. This compares the **set** of `entry_id`s in `entries` with the set
in each index, and fails loudly on any difference.

Exit code 1 on any failure, so a build can gate on it:

    python tools/validate_fts.py --db build/dictionary.sqlite

It also re-runs representative queries, because an index whose ids all match can
still be empty inside (a failed insert into an fts5 table does not always raise).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(BACKEND, "data", "build", "dictionary.sqlite")

INDEXES = {
    "fts": {"columns": ("simplified", "traditional", "pinyin_search", "english", "category", "entry_id"),
            "probe": "simplified"},
    "fts_zh": {"columns": ("simplified", "traditional", "english", "entry_id"),
               "probe": "simplified"},
}

#: Words a working index must find. `一天` and `一年` were among the 76 rows that
#: went missing in the shipped asset, so they are probes, not decoration.
#: Sampling matters per tokenizer: `fts` is unicode61 and can match a single
#: character, `fts_zh` is trigram and can only match strings of 3+ characters —
#: a 0 for `的` in a trigram index says nothing about missing rows.
PROBES = ("一天", "一年", "的", "水")
PROBES_TRIGRAM = ("图书馆", "计算机", "天气")


class FtsValidationError(RuntimeError):
    """Raised by ``require_ok`` so a build step fails closed."""


def _ids(conn, table):
    try:
        rows = conn.execute("select cast(entry_id as integer) from %s" % table).fetchall()
    except sqlite3.OperationalError as exc:
        return None, str(exc)
    return [r[0] for r in rows], None


def _probes(conn, table, tokenizer):
    """Probe words that this tokenizer can actually match.

    Fixed words when they exist in the dictionary, plus words sampled from the
    entries table so a tiny test database is still meaningfully probed.
    """
    fixed = PROBES if tokenizer != "trigram" else PROBES_TRIGRAM + PROBES
    sampled = [r[0] for r in conn.execute(
        "select simplified from entries where simplified is not null "
        "and length(simplified) >= ? group by simplified limit 6",
        (3 if tokenizer == "trigram" else 1,))]
    order = list(fixed) + sampled
    seen, out = set(), []
    for word in order:
        if word and word not in seen:
            seen.add(word)
            out.append(word)
    return out


def _tokenizer(conn, table):
    try:
        sql = conn.execute(
            "select sql from sqlite_master where type='table' and name=?", (table,)).fetchone()
    except sqlite3.OperationalError:
        return "unknown"
    return "trigram" if sql and "trigram" in (sql[0] or "").lower() else "unicode61"


def check(path, probes=None):
    result = {"database": path, "indexes": {}, "ok": True, "failures": []}
    if not os.path.exists(path):
        result["ok"] = False
        result["failures"].append("database missing: %s" % path)
        return result

    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    try:
        entry_ids = [r[0] for r in conn.execute("select entry_id from entries")]
        entry_set = set(entry_ids)
        result["entries"] = {"rows": len(entry_ids), "distinct": len(entry_set)}

        for table, spec in INDEXES.items():
            ids, error = _ids(conn, table)
            if ids is None:
                result["indexes"][table] = {"exists": False, "error": error}
                result["ok"] = False
                result["failures"].append("%s: %s" % (table, error))
                continue
            id_set = set(ids)
            duplicates = len(ids) - len(id_set)
            missing = sorted(entry_set - id_set)
            unexpected = sorted(id_set - entry_set)
            tokenizer = _tokenizer(conn, table)
            words = probes if probes is not None else _probes(conn, table, tokenizer)
            hits = {}
            for word in words:
                try:
                    hits[word] = conn.execute(
                        "select count(*) from %s where %s match ?" % (table, spec["probe"]),
                        (word,)).fetchone()[0]
                except sqlite3.OperationalError as exc:
                    hits[word] = "error: %s" % exc
            entry = {
                "exists": True,
                "rows": len(ids),
                "distinct": len(id_set),
                "duplicates": duplicates,
                "missing": len(missing),
                "missing_sample": missing[:8],
                "unexpected": len(unexpected),
                "unexpected_sample": unexpected[:8],
                "tokenizer": tokenizer,
                "probe_hits": hits,
                "rows_match_entries": len(ids) == len(entry_ids),
            }
            if missing or unexpected or duplicates:
                result["ok"] = False
                result["failures"].append(
                    "%s: %d missing, %d unexpected, %d duplicate ids"
                    % (table, len(missing), len(unexpected), duplicates))
            if not any(isinstance(v, int) and v > 0 for v in hits.values()):
                result["ok"] = False
                result["failures"].append("%s: no probe word is findable" % table)
            result["indexes"][table] = entry

        result["integrity"] = conn.execute("pragma quick_check").fetchone()[0]
        if result["integrity"] != "ok":
            result["ok"] = False
            result["failures"].append("integrity: %s" % result["integrity"])
    finally:
        conn.close()
    return result


def require_ok(path, label="dictionary"):
    """Fail closed: raise when the index set does not match the base table."""
    report = check(path)
    if not report["ok"]:
        raise FtsValidationError(
            "FTS validation failed for %s (%s): %s"
            % (label, path, "; ".join(report["failures"])))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    report = check(args.db)
    if not args.quiet:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report["ok"]:
        print("FTS validation FAILED: %s" % "; ".join(report["failures"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
