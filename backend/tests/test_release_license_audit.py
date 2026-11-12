"""The licence gate must fail the release build, not warn about it.

These tests run the real `audit()` from `tools/build_release_db.py` against a
tiny fixture database, so they are fast and they prove the gate itself works —
not that a particular 114 MB file happens to be clean today.
"""

from __future__ import annotations

import os
import sqlite3
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BACKEND, "tools"))

import build_release_db as release  # noqa: E402


def _fixture(tmp_path, *, provenance=None, extra_tables=(), senses_without_prov=0):
    con = sqlite3.connect(tmp_path / "fixture.sqlite")
    con.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE senses (sense_id INTEGER PRIMARY KEY, gloss_zh TEXT);
        CREATE TABLE gloss_provenance (sense_id INTEGER PRIMARY KEY, source TEXT,
                                       license TEXT);
        """
    )
    con.execute("INSERT INTO meta VALUES ('schema_version', 'v005')")
    con.execute("INSERT INTO meta VALUES ('dataset_version', '2')")
    for source, license_value in provenance or []:
        con.execute("INSERT INTO senses (gloss_zh) VALUES ('释义')")
        sense_id = con.execute("SELECT max(sense_id) FROM senses").fetchone()[0]
        con.execute("INSERT INTO gloss_provenance VALUES (?,?,?)",
                    (sense_id, source, license_value))
    for _ in range(senses_without_prov):
        con.execute("INSERT INTO senses (gloss_zh) VALUES ('无来源')")
    for table in extra_tables:
        con.execute(f"CREATE TABLE {table} (x INTEGER)")
    con.commit()
    return con


def test_clean_fixture_passes(tmp_path):
    con = _fixture(tmp_path, provenance=[("CC-CEDICT", "CC BY-SA 4.0"),
                                          ("zh.wiktionary", "CC BY-SA 4.0")])
    assert release.audit(con) == []
    con.close()


def test_xinhua_provenance_blocks_the_release(tmp_path):
    con = _fixture(tmp_path, provenance=[("xinhua-dictionary", "unclear")])
    problems = release.audit(con)
    assert any("licence-restricted provenance" in p for p in problems)
    con.close()


def test_moedict_provenance_blocks_the_release(tmp_path):
    con = _fixture(tmp_path, provenance=[("MoEDict", "CC BY-ND")])
    problems = release.audit(con)
    assert any("licence-restricted provenance" in p for p in problems)
    con.close()


def test_unknown_source_is_not_silently_accepted(tmp_path):
    con = _fixture(tmp_path, provenance=[("some-scrape", "unknown")])
    problems = release.audit(con)
    assert any("unexpected provenance source" in p for p in problems)
    con.close()


def test_candidate_table_blocks_the_release(tmp_path):
    con = _fixture(tmp_path, provenance=[("CC-CEDICT", "CC BY-SA 4.0")],
                   extra_tables=["gloss_zh_candidates"])
    problems = release.audit(con)
    assert any("forbidden table present: gloss_zh_candidates" in p for p in problems)
    con.close()


def test_chinese_definition_without_provenance_blocks_the_release(tmp_path):
    con = _fixture(tmp_path, senses_without_prov=3)
    problems = release.audit(con)
    assert any("without provenance" in p for p in problems)
    con.close()


def test_drop_forbidden_removes_the_tables_and_audit_then_passes(tmp_path):
    con = _fixture(tmp_path, provenance=[("CC-CEDICT", "CC BY-SA 4.0")],
                   extra_tables=["gloss_zh_candidates", "review_audit"])
    assert any("forbidden table" in p for p in release.audit(con))
    dropped = release.drop_forbidden(con)
    assert set(dropped) == {"gloss_zh_candidates", "review_audit"}
    assert release.audit(con) == []
    con.close()
