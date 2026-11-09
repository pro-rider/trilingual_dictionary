"""Phase 2.1 acceptance gates: transactional import, FTS exact-ID completeness,
human-verification lifecycle. Every check here fails closed."""
from __future__ import annotations

import sqlite3
import time

import pytest

from app.translations import schema
from tools import import_legacy_ne as legacy
from tools import validate_fts

NOW = "2026-11-09T00:00:00Z"


def _dictionary(path, rows=4):
    conn = sqlite3.connect(path)
    conn.execute("create table meta(key text primary key, value text)")
    conn.executemany("insert into meta(key,value) values(?,?)",
                     [("dataset_version", "9"), ("built_at", "2026-11-08T00:06:54")])
    conn.execute("create table entries(entry_id integer primary key, simplified text, pinyin_plain text)")
    conn.execute("""create table senses(sense_id integer primary key, entry_id integer, gloss_en text,
                    gloss_ne text, ne_status text, source_id integer)""")
    conn.executemany("insert into entries values(?,?,?)",
                     [(i, "词%d" % i, "ci%d" % i) for i in range(1, rows + 1)])
    conn.executemany("insert into senses values(?,?,?,?,?,?)",
                     [(i, i, "gloss %d" % i, "अर्थ %d" % i, "ai_translated", 1) for i in range(1, rows + 1)])
    conn.commit()
    conn.close()


def _store(tmp_path):
    store = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(store)
    return store


def _planned(dictionary, dv="dictionary-9@2026-11-08T00:06:54"):
    meta, rows = legacy.read_dictionary(dictionary)
    return legacy.plan(rows, dv)[0]


# ---------------------------------------------------------------- Gate B


def test_import_commits_atomically(tmp_path):
    dictionary = str(tmp_path / "dictionary.sqlite")
    _dictionary(dictionary)
    store = _store(tmp_path)
    result = legacy.apply(_planned(dictionary), store, "dv", "b1")
    assert result == {"batch": "b1", "inserted": 4, "duplicates_skipped": 0}
    conn = schema.connect(store)
    assert conn.execute("select count(*) from translations").fetchone()[0] == 4
    assert conn.execute("select count(*) from id_map").fetchone()[0] == 4
    assert conn.execute("select count(*) from event_log").fetchone()[0] == 4
    conn.close()


@pytest.mark.parametrize("fail_after", [0, 1, 3])
def test_failure_in_the_middle_leaves_no_partial_batch(tmp_path, fail_after):
    dictionary = str(tmp_path / "dictionary.sqlite")
    _dictionary(dictionary)
    store = _store(tmp_path)
    with pytest.raises(RuntimeError):
        legacy.apply(_planned(dictionary), store, "dv", "b1", fail_after=fail_after)
    conn = schema.connect(store)
    # Nothing at all: no rows, no id_map, no audit of a batch that never existed.
    assert conn.execute("select count(*) from translations").fetchone()[0] == 0
    assert conn.execute("select count(*) from id_map").fetchone()[0] == 0
    assert conn.execute("select count(*) from event_log").fetchone()[0] == 0
    assert conn.execute("select count(*) from versions where component='import'").fetchone()[0] == 0
    conn.close()
    # And the same code path still works afterwards.
    result = legacy.apply(_planned(dictionary), store, "dv", "b1")
    assert result["inserted"] == 4


def test_rollback_removes_only_its_batch_and_keeps_audit(tmp_path):
    dictionary = str(tmp_path / "dictionary.sqlite")
    _dictionary(dictionary)
    store = _store(tmp_path)
    legacy.apply(_planned(dictionary), store, "dv", "b1")

    # An unrelated row that must survive.
    conn = schema.connect(store)
    conn.execute(
        "insert into translations(sense_key, entry_key, language, text, created_at, import_batch) "
        "values('other','other','ne','अन्य',?, 'b2')", (NOW,))
    conn.commit()
    audit_before = conn.execute("select count(*) from event_log").fetchone()[0]
    conn.close()

    rolled = legacy.rollback_batch(store, "b1")
    assert rolled["deleted"] == 4
    assert rolled["audit_preserved"] is True

    conn = schema.connect(store)
    assert conn.execute("select count(*) from translations").fetchone()[0] == 1
    assert conn.execute("select text from translations").fetchone()[0] == "अन्य"
    # Import events stay, and the withdrawal itself is recorded.
    assert conn.execute("select count(*) from event_log").fetchone()[0] >= audit_before + 1
    assert conn.execute(
        "select count(*) from event_log where action='rollback_import_batch'").fetchone()[0] == 1
    # id_map is a dictionary-id map, not a claim about rows, so it is kept.
    assert conn.execute("select count(*) from id_map").fetchone()[0] == 4
    conn.close()


CONTENT_COLUMNS = (
    "sense_key", "entry_key", "language", "text", "generation_method", "evidence_strength",
    "validation_status", "publication_status", "human_verification", "origin_source",
    "origin_record_id", "origin_method", "origin_source_version", "legacy_status",
    "import_batch", "evidence_language", "sense_match_method",
)


def _content_set(store):
    """Rows minus timestamps and autoincrement ids: what the import determines."""
    conn = schema.connect(store)
    rows = conn.execute(
        "select %s from translations order by sense_key" % ", ".join(CONTENT_COLUMNS)).fetchall()
    conn.close()
    return rows


def test_reimport_after_rollback_is_deterministic(tmp_path):
    dictionary = str(tmp_path / "dictionary.sqlite")
    _dictionary(dictionary)
    store = _store(tmp_path)
    rows = _planned(dictionary)
    legacy.apply(rows, store, "dv", "b1")
    first = _content_set(store)
    legacy.rollback_batch(store, "b1")
    legacy.apply(rows, store, "dv", "b1")
    second = _content_set(store)
    # Same content, same order. Timestamps and autoincrement ids legitimately
    # differ between runs; the values that carry meaning must not.
    assert first == second
    assert schema.content_fingerprint(store)["integrity"] == "ok"


def test_concurrent_writer_cannot_interleave(tmp_path):
    dictionary = str(tmp_path / "dictionary.sqlite")
    _dictionary(dictionary)
    store = _store(tmp_path)
    rows = _planned(dictionary)

    holder = schema.connect(store)
    holder.isolation_level = None
    holder.execute("BEGIN IMMEDIATE")
    other = schema.connect(store)
    other.execute("pragma busy_timeout = 0")
    with pytest.raises(sqlite3.OperationalError):
        other.execute("BEGIN IMMEDIATE")
    holder.execute("ROLLBACK")
    holder.close()
    other.close()
    # The blocked writer left no trace.
    conn = schema.connect(store)
    assert conn.execute("select count(*) from translations").fetchone()[0] == 0
    conn.close()
    assert legacy.apply(rows, store, "dv", "b1")["inserted"] == 4


# ---------------------------------------------------------------- Gate E


def _authority(conn, role="reviewer", authorized=1, name="surendra"):
    conn.execute(
        "insert into verification_authorities(name, role, authorized, created_at) values(?,?,?,?)",
        (name, role, authorized, NOW))
    return conn.execute("select last_insert_rowid()").fetchone()[0]


def _verified_row(conn, text="पानी", sense_key="k", authority=None, reviewer="surendra"):
    conn.execute(
        """insert into translations(sense_key, entry_key, language, text, generation_method,
           evidence_strength, validation_status, publication_status, human_verification,
           verification_authority_id, reviewer, created_at)
           values(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sense_key, "e", "ne", text, "source_import", "direct", "passed", "published",
         "verified", authority, reviewer, NOW))
    return conn.execute("select last_insert_rowid()").fetchone()[0]


def test_verified_row_needs_an_authorised_reviewer(tmp_path):
    store = _store(tmp_path)
    conn = schema.connect(store)
    with pytest.raises(sqlite3.IntegrityError):
        _verified_row(conn, authority=None, reviewer="someone")
    unauthorised = _authority(conn, authorized=0, name="pending")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _verified_row(conn, authority=unauthorised)
    ok = _authority(conn, name="real-reviewer")
    conn.commit()
    tid = _verified_row(conn, authority=ok)
    conn.commit()
    assert conn.execute("select human_verification from translations where translation_id=?",
                        (tid,)).fetchone()[0] == "verified"
    conn.close()


def test_verified_row_is_immutable_and_append_only(tmp_path):
    store = _store(tmp_path)
    conn = schema.connect(store)
    authority = _authority(conn)
    conn.commit()
    tid = _verified_row(conn, authority=authority)
    conn.commit()

    for sql in ("update translations set text='जल' where translation_id=?",
                "update translations set human_verification='not_verified' where translation_id=?",
                "delete from translations where translation_id=?"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, (tid,))
    conn.close()


def test_verified_row_can_only_be_superseded_by_a_verified_row(tmp_path):
    store = _store(tmp_path)
    conn = schema.connect(store)
    authority = _authority(conn)
    conn.commit()
    tid = _verified_row(conn, authority=authority)
    conn.commit()

    # The pipeline trying to replace a human-verified value is refused.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """insert into translations(sense_key, entry_key, language, text, generation_method,
               publication_status, human_verification, supersedes_id, created_at)
               values('k','e','ne','जल','llm','labeled','not_verified',?,?)""", (tid, NOW))
    # A reviewed correction is accepted, and it is not verified by itself.
    other = _authority(conn, name="second-reviewer")
    conn.commit()
    conn.execute(
        """insert into translations(sense_key, entry_key, language, text, generation_method,
           publication_status, human_verification, verification_authority_id, reviewer,
           supersedes_id, origin_method, created_at)
           values('k','e','ne','जल','legacy_unknown','published','verified',?, 'surendra',
                  ?, 'user_correction', ?)""", (other, tid, NOW))
    new_id = conn.execute("select max(translation_id) from translations").fetchone()[0]
    assert new_id != tid
    assert conn.execute("select human_verification from translations where translation_id=?",
                        (tid,)).fetchone()[0] == "verified"     # history intact
    conn.close()


def test_supersession_must_target_the_leaf_and_stay_in_sense(tmp_path):
    store = _store(tmp_path)
    conn = schema.connect(store)
    conn.execute(
        "insert into translations(sense_key, entry_key, language, text, created_at) "
        "values('k','e','ne','एक',?)", (NOW,))
    first = conn.execute("select max(translation_id) from translations").fetchone()[0]
    conn.execute(
        "insert into translations(sense_key, entry_key, language, text, supersedes_id, created_at) "
        "values('k','e','ne','दुई',?,?)", (first, NOW))
    second = conn.execute("select max(translation_id) from translations").fetchone()[0]
    conn.commit()

    # Branching off the now-superseded first row is refused.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "insert into translations(sense_key, entry_key, language, text, supersedes_id, created_at) "
            "values('k','e','ne','तीन',?,?)", (first, NOW))
    # Jumping to another sense is refused.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "insert into translations(sense_key, entry_key, language, text, supersedes_id, created_at) "
            "values('other','e','ne','चार',?,?)", (second, NOW))
    # A missing target is refused.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "insert into translations(sense_key, entry_key, language, text, supersedes_id, created_at) "
            "values('k','e','ne','पाँच',99999,?)", (NOW,))
    conn.close()


def test_a_pipeline_identity_cannot_become_a_verification_authority(tmp_path):
    store = _store(tmp_path)
    conn = schema.connect(store)
    for role in ("pipeline", "ai", "system"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "insert into verification_authorities(name, role, authorized, created_at) "
                "values('x', ?, 1, ?)", (role, NOW))
    conn.close()


# ---------------------------------------------------------------- resource use


def test_large_batch_import_uses_bounded_memory(tmp_path):
    """A 20k-row batch must not grow memory with the row count.

    Rows are streamed one at a time inside the transaction; only the plan is held.
    This is a guard, not a benchmark: limits are generous but finite.
    """
    import tracemalloc

    dictionary = str(tmp_path / "dictionary.sqlite")
    _dictionary(dictionary, rows=20000)
    store = _store(tmp_path)
    planned = _planned(dictionary)
    tracemalloc.start()
    started = time.perf_counter()
    result = legacy.apply(planned, store, "dv", "big")
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result["inserted"] == 20000
    assert peak < 80 * 1024 * 1024, "peak %.1f MB" % (peak / 1024 / 1024)
    assert elapsed < 60, "20k rows took %.1fs" % elapsed


# ---------------------------------------------------------------- Gate C


def _fts_database(path, entries=5, skip=(), extra=(), duplicates=0):
    conn = sqlite3.connect(path)
    conn.execute("create table entries(entry_id integer primary key, simplified text, "
                 "traditional text, pinyin_search text, english text, category text)")
    conn.execute("create virtual table fts using fts5(simplified, traditional, pinyin_search, "
                 "english, category, entry_id unindexed)")
    conn.execute("create virtual table fts_zh using fts5(simplified, traditional, english, "
                 "entry_id unindexed, tokenize='trigram')")
    words = ["图书馆", "计算机", "天气", "一天", "一年", "水", "书", "的", "火", "山"]
    for i in range(1, entries + 1):
        word = words[(i - 1) % len(words)]
        conn.execute("insert into entries values(?,?,?,?,?,?)",
                     (i, word, word, "ci%d" % i, "gloss %d" % i, "general"))
        if i in skip:
            continue
        conn.execute("insert into fts values(?,?,?,?,?,?)",
                     (word, word, "ci%d" % i, "gloss %d" % i, "general", i))
        for _ in range(1 + (duplicates if i == 1 else 0)):
            conn.execute("insert into fts_zh values(?,?,?,?)",
                         (word, word, "gloss %d" % i, i))
    for i in extra:
        conn.execute("insert into fts values('मन','मन','x','y','general',?)", (i,))
        conn.execute("insert into fts_zh values('मन','मन','y',?)", (i,))
    conn.commit()
    conn.close()


def test_fts_validator_passes_when_every_entry_is_indexed(tmp_path):
    db = str(tmp_path / "dict.sqlite")
    _fts_database(db, entries=5)
    report = validate_fts.check(db)
    assert report["ok"] is True, report["failures"]
    for table in ("fts", "fts_zh"):
        assert report["indexes"][table]["missing"] == 0
        assert report["indexes"][table]["duplicates"] == 0


def test_fts_validator_catches_one_missing_entry(tmp_path):
    db = str(tmp_path / "dict.sqlite")
    _fts_database(db, entries=5, skip={3})
    report = validate_fts.check(db)
    assert report["ok"] is False
    assert report["indexes"]["fts_zh"]["missing"] == 1
    assert report["indexes"]["fts_zh"]["missing_sample"] == [3]
    with pytest.raises(validate_fts.FtsValidationError):
        validate_fts.require_ok(db)


def test_fts_validator_catches_the_76_missing_pattern(tmp_path):
    db = str(tmp_path / "dict.sqlite")
    _fts_database(db, entries=80, skip=set(range(5, 81)))
    report = validate_fts.check(db)
    assert report["ok"] is False
    assert report["indexes"]["fts_zh"]["missing"] == 76


def test_fts_validator_catches_unexpected_and_duplicate_ids(tmp_path):
    db = str(tmp_path / "dict.sqlite")
    _fts_database(db, entries=5, extra={99}, duplicates=1)
    report = validate_fts.check(db)
    assert report["ok"] is False
    assert report["indexes"]["fts_zh"]["unexpected"] == 1
    assert report["indexes"]["fts_zh"]["duplicates"] == 1


def test_fts_validator_reports_a_failed_exit_code(tmp_path, capsys):
    db = str(tmp_path / "dict.sqlite")
    _fts_database(db, entries=5, skip={2})
    assert validate_fts.main(["--db", db]) == 1
    assert "FAILED" in capsys.readouterr().err
    _fts_database(str(tmp_path / "ok.sqlite"), entries=5)
    assert validate_fts.main(["--db", str(tmp_path / "ok.sqlite")]) == 0
