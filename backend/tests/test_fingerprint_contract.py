"""Contract tests for the canonical content fingerprint.

Two databases with the same logical content must hash identically even if rows
were inserted in a different order, or a copy was made through SQLite's backup
API; any real value change, including NULL vs empty string, must change the hash.
"""
from __future__ import annotations

import os
import sqlite3
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.translations import schema  # noqa: E402

DDL = """
create table things(id integer primary key, name text, note text);
create table unordered(name text, note text);
"""


def _make(path, rows, unordered_rows):
    conn = sqlite3.connect(path)
    conn.executescript(DDL)
    conn.executemany("insert into things(id, name, note) values(?,?,?)", rows)
    conn.executemany("insert into unordered(name, note) values(?,?)", unordered_rows)
    conn.commit()
    conn.close()
    return str(path)


def test_same_content_in_a_different_insert_order_hashes_the_same(tmp_path):
    rows = [(1, "water", "पानी"), (2, "fire", None), (3, "book", "किताब")]
    a = _make(tmp_path / "a.db", rows, [("z", "1"), ("a", "2")])
    b = _make(tmp_path / "b.db", list(reversed(rows)), [("a", "2"), ("z", "1")])
    assert schema.content_fingerprint(a)["content_sha256"] == \
        schema.content_fingerprint(b)["content_sha256"]


def test_a_copy_made_by_sqlite_hashes_the_same_but_file_bytes_may_differ(tmp_path):
    a = _make(tmp_path / "a.db", [(1, "water", "पानी")], [("z", "1")])
    b = str(tmp_path / "b.db")
    src, dst = sqlite3.connect(a), sqlite3.connect(b)
    src.backup(dst)
    src.close()
    dst.close()
    assert schema.content_fingerprint(a)["content_sha256"] == \
        schema.content_fingerprint(b)["content_sha256"]


def test_null_and_empty_string_are_different(tmp_path):
    a = _make(tmp_path / "a.db", [(1, "water", None)], [])
    b = _make(tmp_path / "b.db", [(1, "water", "")], [])
    assert schema.content_fingerprint(a)["content_sha256"] != \
        schema.content_fingerprint(b)["content_sha256"]


def test_a_single_character_change_changes_the_hash(tmp_path):
    a = _make(tmp_path / "a.db", [(1, "water", "पानी")], [])
    b = _make(tmp_path / "b.db", [(1, "water", "पानी ")], [])   # trailing space
    assert schema.content_fingerprint(a)["content_sha256"] != \
        schema.content_fingerprint(b)["content_sha256"]


def test_a_schema_bump_is_visible_in_the_fingerprint(tmp_path):
    a = _make(tmp_path / "a.db", [(1, "water", "पानी")], [])
    conn = sqlite3.connect(a)
    conn.execute("pragma user_version = 9")
    conn.commit()
    conn.close()
    b = _make(tmp_path / "b.db", [(1, "water", "पानी")], [])
    assert schema.content_fingerprint(a)["content_sha256"] != \
        schema.content_fingerprint(b)["content_sha256"]


def test_a_value_containing_the_field_separator_cannot_imitate_two_fields(tmp_path):
    """Without length prefixes ("x\\x1ey","") and ("x","y") would collide."""
    a = _make(tmp_path / "a.db", [(1, "x\x1ey", "")], [])
    b = _make(tmp_path / "b.db", [(1, "x", "y")], [])
    assert schema.content_fingerprint(a)["content_sha256"] != \
        schema.content_fingerprint(b)["content_sha256"]


def test_a_field_containing_a_chunk_separator_cannot_imitate_a_row(tmp_path):
    a = _make(tmp_path / "a.db", [(1, "x\x1d", "")], [])
    b = _make(tmp_path / "b.db", [(1, "x", "")], [])   # also one row, different text
    assert schema.content_fingerprint(a)["content_sha256"] != \
        schema.content_fingerprint(b)["content_sha256"]


def test_the_fingerprint_carries_its_definition_version(tmp_path):
    a = _make(tmp_path / "a.db", [(1, "water", "पानी")], [])
    result = schema.content_fingerprint(a)
    assert result["fingerprint_version"] == schema.FINGERPRINT_VERSION == 1
    assert result["integrity"] == "ok"
