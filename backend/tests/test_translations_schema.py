"""Schema 2 tests — dimensions, legacy mapping, verification triggers,
quarantine metadata, migration and rollback."""
from __future__ import annotations

import json
import sqlite3

import pytest

from app.translations import schema

NOW = "2026-11-09T00:00:00Z"


def _make_v1_store(path, rows=()):
    """Build a real schema-1 store, including its three triggers."""
    conn = sqlite3.connect(path)
    for stmt in schema._TABLES_V1:
        conn.execute(stmt)
    conn.execute("pragma user_version = 1")
    for row in rows:
        conn.execute(
            """
            insert into translations(translation_id, sense_key, entry_key, language, text,
                                    status, source_type, evidence_category, evidence_ids,
                                    model_version, prompt_version, confidence, flags,
                                    reviewer, reviewed_at, created_at)
            values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            row,
        )
    conn.commit()
    conn.close()


def _insert_v2(conn, *, text="पानी", verification="not_verified", authority=None,
               reviewer=None, publication="labeled", reason=None, method="llm",
               strength="none", validation="incomplete", source=None):
    conn.execute(
        """
        insert into translations(sense_key, entry_key, language, text, generation_method,
                                 evidence_strength, validation_status, publication_status,
                                 human_verification, verification_authority_id,
                                 origin_source, quarantine_reason, reviewer, created_at)
        values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (schema.sense_key("水", "shui", "water"), schema.entry_key("水", "shui"), "ne",
         text, method, strength, validation, publication, verification, authority,
         source, reason, reviewer, NOW),
    )


def _authorize(conn):
    conn.execute(
        "insert into verification_authorities(name, role, authorized, created_at) "
        "values('surendra','reviewer',1,?)", (NOW,))
    return conn.execute("select authority_id from verification_authorities").fetchone()[0]


def test_fresh_store_is_at_the_current_schema_with_governance_tables(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    report = schema.migrate(db)
    assert report["to_version"] == schema.SCHEMA_VERSION
    conn = sqlite3.connect(db)
    assert schema.user_version(conn) == schema.SCHEMA_VERSION
    tables = schema.table_names(conn)
    for name in ("translations", "evidence", "versions", "id_map", "verification_authorities",
                 "sense_pos", "sense_hsk", "entry_aliases", "sense_aliases",
                 "id_collisions", "quarantine_records", "user_corrections", "event_log"):
        assert name in tables, name
    triggers = schema.trigger_names(conn)
    for name in ("translations_verified_immutable_update",
                 "translations_verified_immutable_delete",
                 "translations_verification_is_append_only",
                 "translations_verification_requires_authority",
                 "translations_quarantine_needs_reason"):
        assert name in triggers, name
    conn.close()


def test_legacy_rows_map_to_dimensions_and_keep_ids(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    rows = [
        (1, "k1", "e1", "ne", "पानी", "reviewed", "human", "A", json.dumps([]), None, None, 0.9, None, "surendra", NOW, NOW),
        (2, "k2", "e2", "ne", "जल", "verified", "dict", "B", json.dumps([]), None, None, 0.8, None, "old-reviewer", NOW, NOW),
        (3, "k3", "e3", "ne", "दिन", "ai_checked", "ai", "A", json.dumps([]), "gpt-oss-120b", "p1", 0.7, None, None, None, NOW),
        (4, "k4", "e4", "ne", "बाटो", "ai_unverified", "ai", None, json.dumps([]), "gpt-oss-120b", "p1", 0.5, None, None, None, NOW),
        (5, "k5", "e5", "ne", "कुकुर", "quarantined", "import", None, json.dumps([]), None, None, 0.1, None, None, None, NOW),
    ]
    _make_v1_store(db, rows)
    report = schema.migrate(db)
    assert report["from_version"] == 1
    assert report["backup"] and report["backup"].startswith(db + ".bak-")

    conn = sqlite3.connect(db)
    got = {
        r[0]: r[1:] for r in conn.execute(
            "select translation_id, legacy_status, generation_method, evidence_strength, "
            "validation_status, publication_status, human_verification, reviewer "
            "from translations order by translation_id"
        )
    }
    assert got[1] == ("reviewed", "source_import", "direct", "incomplete", "labeled", "not_verified", "surendra")
    # a legacy "verified" row is NOT human verification, and evidence B -> strong
    assert got[2] == ("verified", "source_import", "strong", "incomplete", "labeled", "not_verified", "old-reviewer")
    assert got[3] == ("ai_checked", "llm", "direct", "passed", "labeled", "not_verified", None)
    assert got[4] == ("ai_unverified", "llm", "none", "incomplete", "labeled", "not_verified", None)
    assert got[5][0] == "quarantined" and got[5][3] == "failed" and got[5][4] == "quarantined"
    assert conn.execute("select count(*) from translations").fetchone()[0] == 5

    events = conn.execute(
        "select action, note from event_log where action='map_legacy_status'"
    ).fetchall()
    assert len(events) == 5
    assert all("not evidence of human verification" in e[1] for e in events)
    conn.close()


def test_pipeline_cannot_set_human_verified(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(db)
    conn = schema.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_v2(conn, verification="verified", reviewer="bot")   # no authority
    conn.close()


def test_authorised_verification_is_accepted_then_immutable(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(db)
    conn = schema.connect(db)
    authority = _authorize(conn)
    _insert_v2(conn, verification="verified", reviewer="surendra", authority=authority,
               publication="published")
    conn.commit()
    tid = conn.execute("select translation_id from translations").fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError):   # cannot edit it
        conn.execute("update translations set text='जल' where translation_id=?", (tid,))
    with pytest.raises(sqlite3.IntegrityError):   # cannot delete it
        conn.execute("delete from translations where translation_id=?", (tid,))
    conn.close()


def test_verification_state_is_append_only(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(db)
    conn = schema.connect(db)
    _insert_v2(conn, verification="not_verified")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("update translations set human_verification='verified'")
    conn.close()


def test_verification_needs_a_reviewer_name(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(db)
    conn = schema.connect(db)
    authority = _authorize(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_v2(conn, verification="verified", reviewer=None, authority=authority)
    conn.close()


def test_quarantine_needs_reason_and_keeps_original_text(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(db)
    conn = schema.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_v2(conn, publication="quarantined", text="बatti")
    conn.execute(
        """
        insert into translations(sense_key, entry_key, language, text, generation_method,
                                 evidence_strength, validation_status, publication_status,
                                 quarantine_reason, quarantine_rule, quarantine_batch,
                                 quarantined_at, created_at)
        values(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        ("k", "e", "ne", "बatti", "legacy_unknown", "none", "failed", "quarantined",
         "mixed Latin letters inside a Devanagari string", "mixed_script", "batch-001", NOW, NOW),
    )
    tid = conn.execute("select translation_id from translations").fetchone()[0]
    conn.execute(
        "insert into quarantine_records(translation_id, sense_key, original_text, reason, rule, batch_id, quarantined_at) "
        "values(?,?,?,?,?,?,?)",
        (tid, "k", "बatti", "mixed script", "mixed_script", "batch-001", NOW),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "insert into quarantine_records(sense_key, original_text, reason, quarantined_at) "
            "values('k', '  ', 'x', ?)", (NOW,))
    conn.commit()
    stored = conn.execute("select original_text from quarantine_records").fetchone()[0]
    assert stored == "बatti"        # the original value is recoverable, not replaced
    conn.close()


def test_unknown_schema_version_fails_loudly(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    conn = sqlite3.connect(db)
    conn.execute("pragma user_version = 7")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError):
        schema.migrate(db)


def test_rollback_restores_content(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    _make_v1_store(db, [(1, "k", "e", "ne", "पानी", "reviewed", "human", "A",
                         json.dumps([]), None, None, 0.5, None, "r", NOW, NOW)])
    before = schema.snapshot(db)
    report = schema.migrate(db)
    assert schema.snapshot(db) != before
    schema.rollback(db, report["backup"])
    after = schema.snapshot(db)
    assert after["user_version"] == before["user_version"] == 1
    assert after["counts"]["translations"] == 1
    assert after["tables"] == before["tables"]


def test_dry_run_touches_nothing(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    report = schema.migrate(db, dry_run=True)
    assert not (tmp_path / schema.DB_FILENAME).exists()
    assert "would create" in report["actions"][0]


def test_sense_key_is_stable():
    assert schema.sense_key("水", "shui", "water") == schema.sense_key(" 水 ", "SHUI ", " Water ")
    assert schema.sense_key("水", "shui", "river") != schema.sense_key("水", "shui", "water")
