"""Ledger schema verification: fail closed, never repair.

The previous verifier only looked at table names and a metadata row.  A table
set can be complete while a UNIQUE constraint, an index, or a column type is
wrong — and the ledger would happily run on it.  This module compares the
*full* structure (columns, declared types, nullability, primary keys, unique
constraints, indexes, foreign keys, and normalised DDL) against a pristine
database built from the same DDL.

On any difference it raises and reports every difference it found; it never
alters the live database.
"""

from __future__ import annotations

import hashlib
import sqlite3

from .schema import EXPECTED_INDEXES, EXPECTED_TABLES, SCHEMA_STATEMENTS


class LedgerSchemaMismatch(RuntimeError):
    """The ledger file is not the schema this code owns."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("ledger schema mismatch: " + "; ".join(self.problems))


def _normalise_sql(sql: str | None) -> str:
    if not sql:
        return ""
    return " ".join(sql.split()).lower()


def introspect(conn: sqlite3.Connection) -> dict:
    """Structural description of every user table in a connection."""
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    description: dict[str, dict] = {}
    for table in tables:
        columns = [
            {
                "name": row[1],
                "type": (row[2] or "").upper(),
                "notnull": int(row[3]),
                "default": row[4],
                "pk": int(row[5]),
            }
            for row in conn.execute(f'PRAGMA table_info("{table}")')
        ]
        indexes = []
        for idx in conn.execute(f'PRAGMA index_list("{table}")'):
            name = idx[1]
            # index_info() reports NULL as the column name for an expression
            # index, so the expression itself is invisible there.  The index DDL
            # is the only complete description: it carries the expression,
            # COLLATE, ASC/DESC and the partial-index predicate.
            idx_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)
            ).fetchone()
            indexes.append(
                {
                    "name": name,
                    "unique": int(idx[2]),
                    "columns": [r[2] for r in conn.execute(f'PRAGMA index_info("{name}")')],
                    "partial": int(idx[4]) if len(idx) > 4 else 0,
                    "ddl_sha256": hashlib.sha256(
                        _normalise_sql(idx_sql[0] if idx_sql else "").encode("utf-8")
                    ).hexdigest(),
                }
            )
        foreign_keys = [
            {
                "table": row[2],
                "from": row[3],
                "to": row[4],
                "on_delete": row[6],
            }
            for row in conn.execute(f'PRAGMA foreign_key_list("{table}")')
        ]
        ddl_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        description[table] = {
            "columns": columns,
            "indexes": indexes,
            "foreign_keys": foreign_keys,
            "ddl_sha256": hashlib.sha256(
                _normalise_sql(ddl_row[0] if ddl_row else "").encode("utf-8")
            ).hexdigest(),
        }
    return description


def expected_structure() -> dict:
    """Build the expected schema in memory and describe it."""
    conn = sqlite3.connect(":memory:")
    try:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        return introspect(conn)
    finally:
        conn.close()


_EXPECTED = None


def _expected() -> dict:
    global _EXPECTED
    if _EXPECTED is None:
        _EXPECTED = expected_structure()
    return _EXPECTED


def _user_indexes(indexes: list[dict]) -> dict[str, dict]:
    """Drop SQLite's implicit autoindexes: they follow the constraints, not our names."""
    return {
        idx["name"]: idx
        for idx in indexes
        if not idx["name"].startswith("sqlite_autoindex_")
    }


def verify(conn: sqlite3.Connection) -> dict:
    expected = _expected()
    live = introspect(conn)
    problems: list[str] = []

    missing_tables = EXPECTED_TABLES - set(live)
    if missing_tables:
        problems.append(f"missing tables {sorted(missing_tables)}")
    extra_tables = set(live) - EXPECTED_TABLES
    if extra_tables:
        problems.append(f"unexpected tables {sorted(extra_tables)}")

    for table in sorted(EXPECTED_TABLES & set(live)):
        want, got = expected[table], live[table]

        want_cols = [(c["name"], c["type"], c["notnull"], c["pk"]) for c in want["columns"]]
        got_cols = [(c["name"], c["type"], c["notnull"], c["pk"]) for c in got["columns"]]
        if want_cols != got_cols:
            problems.append(f"{table}.columns differ: expected {want_cols} got {got_cols}")

        want_idx = {
            (t["unique"], tuple(t["columns"]), t["partial"], t["ddl_sha256"])
            for t in _user_indexes(want["indexes"]).values()
        }
        got_idx = {
            (t["unique"], tuple(t["columns"]), t["partial"], t["ddl_sha256"])
            for t in _user_indexes(got["indexes"]).values()
        }
        if want_idx != got_idx:
            problems.append(f"{table}.indexes differ: expected {sorted(want_idx)} got {sorted(got_idx)}")

        want_named = set(_user_indexes(want["indexes"])) & EXPECTED_INDEXES
        got_named = set(_user_indexes(got["indexes"]))
        missing_idx = want_named - got_named
        if missing_idx:
            problems.append(f"{table}.indexes missing {sorted(missing_idx)}")

        if want["foreign_keys"] != got["foreign_keys"]:
            problems.append(f"{table}.foreign_keys differ")

        if want["ddl_sha256"] != got["ddl_sha256"]:
            problems.append(f"{table}.ddl differs from the expected definition")

    if problems:
        raise LedgerSchemaMismatch(problems)

    return {
        "tables": sorted(live),
        "schema_fingerprint": hashlib.sha256(
            "|".join(
                f"{table}:{live[table]['ddl_sha256']}:{len(live[table]['columns'])}:"
                + ",".join(
                    f"{idx['name']}={idx['ddl_sha256'][:12]}"
                    for idx in sorted(_user_indexes(live[table]["indexes"]).values(), key=lambda i: i["name"])
                )
                for table in sorted(live)
            ).encode("utf-8")
        ).hexdigest(),
    }
