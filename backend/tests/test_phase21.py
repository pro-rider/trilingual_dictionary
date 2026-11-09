"""Phase 2.1 corrections: content-level verification, authority role gate,
legacy import of the real dictionary shape, and reversible quarantine."""
from __future__ import annotations

import sqlite3

import pytest

from app.translations import schema
from tools import import_legacy_ne as legacy

NOW = "2026-11-09T00:00:00Z"


def _tiny_dictionary(path):
    """The minimum shape the importer reads, mirroring the real schema."""
    conn = sqlite3.connect(path)
    conn.execute("create table meta(key text primary key, value text)")
    conn.executemany("insert into meta(key, value) values(?,?)",
                     [("dataset_version", "9"), ("built_at", "2026-11-08T00:06:54")])
    conn.execute("""create table entries(
        entry_id integer primary key, simplified text, pinyin_plain text)""")
    conn.execute("""create table senses(
        sense_id integer primary key, entry_id integer, gloss_en text, gloss_ne text,
        ne_status text, source_id integer)""")
    conn.executemany(
        "insert into entries(entry_id, simplified, pinyin_plain) values(?,?,?)",
        [(1, "水", "shui"), (2, "书", "shu")],
    )
    conn.executemany(
        "insert into senses(sense_id, entry_id, gloss_en, gloss_ne, ne_status, source_id) "
        "values(?,?,?,?,?,?)",
        [(1, 1, "water", "पानी", "ai_translated", 1),
         (2, 1, "river", "खोला", "ai_translated", 1),
         (3, 2, "book", "किताब", "ai_translated", 1),
         (4, 2, "to write", "", "none", 1)],
    )
    conn.commit()
    conn.close()


def test_content_fingerprint_separates_equal_counts_from_equal_content(tmp_path):
    a, b = str(tmp_path / "a.db"), str(tmp_path / "b.db")
    for path, value in ((a, "पानी"), (b, "जल")):
        conn = sqlite3.connect(path)
        conn.execute("create table t(id integer primary key, v text)")
        conn.execute("insert into t(id, v) values(1, ?)", (value,))
        conn.commit()
        conn.close()
    fa, fb = schema.content_fingerprint(a), schema.content_fingerprint(b)
    assert fa["tables"]["t"]["rows"] == fb["tables"]["t"]["rows"] == 1   # same count
    assert fa["content_sha256"] != fb["content_sha256"]                  # different values
    assert fa["integrity"] == "ok"


def test_content_fingerprint_is_stable_for_identical_content(tmp_path):
    a, b = str(tmp_path / "a.db"), str(tmp_path / "b.db")
    for path in (a, b):
        conn = sqlite3.connect(path)
        conn.execute("create table t(id integer primary key, v text)")
        conn.executemany("insert into t(id, v) values(?,?)", [(1, "पानी"), (2, "जल")])
        conn.commit()
        conn.close()
    assert schema.content_fingerprint(a) == schema.content_fingerprint(b)


def test_rollback_reports_content_match(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(db)
    conn = schema.connect(db)
    conn.execute(
        "insert into translations(sense_key, entry_key, language, text, created_at) "
        "values('k','e','ne','पानी',?)", (NOW,))
    conn.commit()
    before = schema.content_fingerprint(db)
    backup = schema.backup(db)
    conn.execute("update translations set text='जल'")
    conn.commit()
    conn.close()
    assert schema.content_fingerprint(db) != before

    result = schema.rollback(db, backup)
    assert result["content_matches_backup"] is True
    assert result["content_sha256"] == schema.content_fingerprint(backup)["content_sha256"]
    assert result["integrity"] == "ok"


def test_verification_authority_must_be_a_human_role(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(db)
    conn = schema.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "insert into verification_authorities(name, role, authorized, created_at) "
            "values('translation-pipeline','pipeline',1,?)", (NOW,))
    conn.execute(
        "insert into verification_authorities(name, role, authorized, created_at) "
        "values('surendra','reviewer',1,?)", (NOW,))
    conn.commit()
    assert conn.execute("select count(*) from verification_authorities").fetchone()[0] == 1
    conn.close()


def test_import_maps_real_dictionary_shape_and_rolls_back(tmp_path):
    dictionary = str(tmp_path / "dictionary.sqlite")
    store = str(tmp_path / schema.DB_FILENAME)
    _tiny_dictionary(dictionary)
    schema.migrate(store)

    meta, rows = legacy.read_dictionary(dictionary)
    assert meta["dataset_version"] == "9"
    assert len(rows) == 3                              # the empty Nepali row is excluded

    data_version = "dictionary-%s@%s" % (meta["dataset_version"], meta["built_at"])
    planned, skipped, problems = legacy.plan(rows, data_version)
    assert (len(planned), skipped, problems) == (3, [], [])

    applied = legacy.apply(planned, store, data_version, "batch-test")
    assert applied == {"batch": "batch-test", "inserted": 3, "duplicates_skipped": 0}

    report = legacy.verify(store, dictionary, "batch-test")
    assert report["ok"] is True
    assert report["imported_rows_checked"] == 3
    assert report["text_mismatches"] == 0

    # A row carries the original sense id and the machine-generation marker only.
    conn = schema.connect(store)
    row = conn.execute(
        "select generation_method, human_verification, origin_record_id, evidence_strength, "
        "validation_status, evidence_language from translations where text='पानी'").fetchone()
    assert row == ("llm", "not_verified", "1", "none", "incomplete", None)
    assert conn.execute("select count(*) from id_map").fetchone()[0] == 3
    conn.close()

    # The import is reversible and never touches the dictionary.
    before = schema.content_fingerprint(dictionary)
    rolled = legacy.rollback_batch(store, "batch-test")
    assert rolled["deleted"] == 3
    assert schema.content_fingerprint(dictionary) == before


def test_import_is_idempotent(tmp_path):
    dictionary = str(tmp_path / "dictionary.sqlite")
    store = str(tmp_path / schema.DB_FILENAME)
    _tiny_dictionary(dictionary)
    schema.migrate(store)
    meta, rows = legacy.read_dictionary(dictionary)
    dv = "dictionary-9@x"
    planned, _s, _p = legacy.plan(rows, dv)
    legacy.apply(planned, store, dv, "b1")
    second = legacy.apply(planned, store, dv, "b2")
    assert second["inserted"] == 0
    assert second["duplicates_skipped"] == 3


def test_quarantine_is_reversible_and_keeps_the_value(tmp_path):
    db = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(db)
    conn = schema.connect(db)
    conn.execute(
        """insert into translations(sense_key, entry_key, language, text, generation_method,
           evidence_strength, validation_status, publication_status, quarantine_reason,
           quarantine_rule, quarantine_batch, quarantined_at, created_at)
           values(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("k", "e", "ne", "बatti", "legacy_unknown", "none", "failed", "quarantined",
         "mixed script", "mixed_script", "batch-001", NOW, NOW),
    )
    tid = conn.execute("select translation_id from translations").fetchone()[0]
    conn.execute(
        "insert into quarantine_records(translation_id, sense_key, original_text, reason, rule, "
        "batch_id, quarantined_at) values(?,?,?,?,?,?,?)",
        (tid, "k", "बatti", "mixed script", "mixed_script", "batch-001", NOW),
    )
    conn.commit()

    # Restore path: flip publication back and stamp the record. The text was never lost.
    conn.execute("update translations set publication_status='labeled', quarantine_reason=null "
                 "where translation_id=?", (tid,))
    conn.execute("update quarantine_records set restored_at=?, restored_by='surendra' "
                 "where translation_id=?", (NOW, tid))
    conn.commit()
    assert conn.execute("select text from translations").fetchone()[0] == "बatti"
    assert conn.execute("select original_text, restored_by from quarantine_records").fetchone() \
        == ("बatti", "surendra")
    conn.close()
