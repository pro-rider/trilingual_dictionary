"""Phase 1 tests — schema, immutability triggers, backup and rollback."""
from __future__ import annotations

import os
import sqlite3

import pytest

from app.translations import schema


def _insert(conn, status="ai_unverified", text="पानी", supersedes=None, reviewer=None):
    conn.execute(
        """
        insert into translations(sense_key, entry_key, language, text, status,
                                 source_type, created_at, supersedes_id, reviewer)
        values(?,?,?,?,?,?,?,?,?)
        """,
        (
            schema.sense_key("水", "shui", "water"),
            schema.entry_key("水", "shui"),
            "ne",
            text,
            status,
            "ai",
            "2026-11-09T00:00:00Z",
            supersedes,
            reviewer,
        ),
    )


def test_fresh_migrate_creates_schema(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    report = schema.migrate(db)
    assert report["existed"] is False
    assert report["to_version"] == schema.SCHEMA_VERSION
    conn = sqlite3.connect(db)
    assert schema.user_version(conn) == 1
    names = schema.table_names(conn)
    for table in ("translations", "evidence", "versions", "id_map"):
        assert table in names
    triggers = [r[0] for r in conn.execute(
        "select name from sqlite_master where type='trigger'")]
    assert "translations_immutable_update" in triggers
    assert "translations_immutable_delete" in triggers
    conn.close()


def test_verified_rows_cannot_be_updated_or_deleted(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(db)
    conn = schema.connect(db)
    _insert(conn, status="reviewed", text="पानी", reviewer="surendra")
    conn.commit()
    row = conn.execute("select translation_id from translations").fetchone()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("update translations set text='जल' where translation_id=?", (row[0],))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("delete from translations where translation_id=?", (row[0],))
    conn.close()


def test_superseding_proposal_is_allowed(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(db)
    conn = schema.connect(db)
    _insert(conn, status="reviewed", text="पानी", reviewer="surendra")
    first = conn.execute("select translation_id from translations").fetchone()[0]
    _insert(conn, status="ai_unverified", text="जल", supersedes=first)
    conn.commit()
    rows = conn.execute(
        "select status, text, supersedes_id from translations order by translation_id"
    ).fetchall()
    assert rows[0] == ("reviewed", "पानी", None)
    assert rows[1] == ("ai_unverified", "जल", first)
    conn.close()


def test_status_and_reviewer_rules(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(db)
    conn = schema.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, status="approved")          # not a legal status
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, status="verified", reviewer=None)   # needs a reviewer
    conn.commit()
    conn.close()


def test_migrate_existing_file_takes_a_backup(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    conn = sqlite3.connect(db)
    conn.execute("create table legacy(x)")        # simulate an existing store at v0
    conn.commit()
    conn.close()
    report = schema.migrate(db)
    assert report["from_version"] == 0
    assert report["backup"] is not None
    assert os.path.exists(report["backup"])
    assert report["backup"].startswith(db + ".bak-")
    assert os.path.getsize(report["backup"]) > 0


def test_rollback_restores_the_previous_file(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    conn = sqlite3.connect(db)
    conn.execute("create table legacy(x)")
    conn.execute("insert into legacy(x) values(1)")
    conn.commit()
    conn.close()

    before = schema.snapshot(db)
    report = schema.migrate(db)
    backup = report["backup"]
    assert schema.snapshot(db) != before           # migrated

    result = schema.rollback(db, backup)
    after = schema.snapshot(db)
    # A rollback is proven by content, not by file hash: SQLite may rewrite
    # page layout when it copies, so identical bytes are not guaranteed.
    assert after["user_version"] == before["user_version"] == 0
    assert after["tables"] == before["tables"] == ["legacy"]
    assert after["counts"] == before["counts"] == {"legacy": 1}
    assert os.path.exists(result["previous_moved_to"])  # the migrated file is kept aside


def test_dry_run_touches_nothing(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    report = schema.migrate(db, dry_run=True)
    assert report["existed"] is False
    assert not os.path.exists(db)


def test_sense_key_is_stable_across_rebuilds(tmp_path):
    a = schema.sense_key("水", "shui", "water")
    b = schema.sense_key(" 水 ", "SHUI ", " Water ")
    assert a == b
    assert schema.sense_key("水", "shui", "river") != a
    assert "\x1f" in a
