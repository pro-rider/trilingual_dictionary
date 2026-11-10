"""Guards for the correction pipeline and the encoding allowlist.

Every test pairs a positive case with the case that must be refused, because a
repair tool that cannot refuse is more dangerous than no repair tool.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from tools import apply_ne_corrections as apply_mod  # noqa: E402
from tools import check_encoding as enc_mod  # noqa: E402
from tools import sync_legacy_translation_text as sync_mod  # noqa: E402
from app.translations import script_mix  # noqa: E402

CORRECTIONS = REPO / "docs" / "NE-CORRECTIONS.json"
ALLOWLIST = REPO / "docs" / "ENCODING-ALLOWLIST.json"
PRODUCTION = BACKEND / "data" / "build" / "dictionary.sqlite"

SCHEMA = {
    "senses": ("CREATE TABLE senses (sense_id INTEGER PRIMARY KEY, entry_id INTEGER,"
               " gloss_en TEXT, gloss_ne TEXT, ne_status TEXT NOT NULL DEFAULT 'none')"),
    "examples": ("CREATE TABLE examples (example_id INTEGER PRIMARY KEY, sense_id INTEGER,"
                 " en TEXT, zh TEXT, ne TEXT, review_status TEXT)"),
}


def _corrections():
    with open(CORRECTIONS, encoding="utf-8") as fh:
        return json.load(fh)["corrections"]


def _make_db(path, records):
    """Build a throwaway database holding exactly the recorded rows plus one bystander."""
    conn = sqlite3.connect(path)
    for ddl in SCHEMA.values():
        conn.execute(ddl)
    for rec in records:
        if rec["table"] == "senses":
            conn.execute("INSERT INTO senses (sense_id, entry_id, gloss_en, gloss_ne, ne_status)"
                         " VALUES (?, ?, ?, ?, 'ai_translated')",
                         (rec["key_value"], rec["key_value"], rec.get("gloss_en"), rec["old"]))
        else:
            conn.execute("INSERT INTO examples (example_id, sense_id, en, zh, ne, review_status)"
                         " VALUES (?, ?, ?, ?, ?, 'unverified')",
                         (rec["key_value"], rec["key_value"], rec.get("gloss_en"), "", rec["old"]))
    conn.execute("INSERT INTO senses (sense_id, entry_id, gloss_en, gloss_ne)"
                 " VALUES (-1, -1, 'bystander', 'अछुत')")
    conn.commit()
    conn.close()


def _read(db, table, key_column, key_value, column):
    conn = sqlite3.connect(db)
    row = conn.execute('SELECT "%s" FROM "%s" WHERE "%s" = ?'
                       % (column, table, key_column), (key_value,)).fetchone()
    conn.close()
    return None if row is None else row[0]


def test_corrections_file_is_well_formed():
    records = _corrections()
    assert records
    identities = [(r["table"], r["key_value"], r["column"]) for r in records]
    assert len(identities) == len(set(identities))
    tables = {r["table"] for r in records}
    assert tables.issubset(set(SCHEMA)), "a correction targets a table the tests do not cover"
    for rec in records:
        assert rec["old"] != rec["new"]
        assert "\ufffd" not in rec["new"], rec
        verdict = script_mix.classify(rec["new"])
        assert not verdict["quarantine_justified"], (rec["new"], verdict)
        assert rec["basis"] and rec["evidence"], rec
        assert rec["confidence"] in ("high", "medium", "low"), rec


def test_dry_run_writes_nothing(tmp_path):
    records = _corrections()
    db = tmp_path / "copy.sqlite"
    _make_db(db, records)
    before = db.read_bytes()

    report = apply_mod.run(db, CORRECTIONS, apply=False, backup=None)

    assert report["verdict"] == "DRY-RUN-OK", report
    assert db.read_bytes() == before
    assert _read(db, records[0]["table"], records[0]["key_column"],
                 records[0]["key_value"], records[0]["column"]) == records[0]["old"]


def test_apply_changes_only_the_recorded_rows(tmp_path):
    records = _corrections()
    db = tmp_path / "copy.sqlite"
    _make_db(db, records)
    backup = tmp_path / "backup.sqlite"
    backup.write_bytes(db.read_bytes())

    report = apply_mod.run(db, CORRECTIONS, apply=True, backup=backup)

    assert report["verdict"] == "APPLIED", report
    assert report["changed_rows"] == len(records)
    for rec in records:
        assert _read(db, rec["table"], rec["key_column"], rec["key_value"],
                     rec["column"]) == rec["new"], rec["key_value"]
    assert _read(db, "senses", "sense_id", -1, "gloss_ne") == "अछुत"


def test_second_run_is_idempotent(tmp_path):
    records = _corrections()
    db = tmp_path / "copy.sqlite"
    _make_db(db, records)
    backup = tmp_path / "backup.sqlite"
    backup.write_bytes(db.read_bytes())

    first = apply_mod.run(db, CORRECTIONS, apply=True, backup=backup)
    assert first["changed_rows"] == len(records)

    second_backup = tmp_path / "backup2.sqlite"
    second_backup.write_bytes(db.read_bytes())
    second = apply_mod.run(db, CORRECTIONS, apply=True, backup=second_backup)

    assert second["verdict"] == "APPLIED", second
    assert second["changed_rows"] == 0
    assert len(second["already_applied"]) == len(records)
    assert second["after_sha256"] == second["before_sha256"]


def test_apply_refuses_on_drift(tmp_path):
    records = _corrections()
    db = tmp_path / "copy.sqlite"
    _make_db(db, records)

    conn = sqlite3.connect(db)
    rec = records[0]
    conn.execute('UPDATE "%s" SET "%s" = ? WHERE "%s" = ?'
                 % (rec["table"], rec["column"], rec["key_column"]),
                 ("बदलियो", rec["key_value"]))
    conn.commit()
    conn.close()
    drifted = db.read_bytes()
    backup = tmp_path / "backup.sqlite"
    backup.write_bytes(drifted)

    report = apply_mod.run(db, CORRECTIONS, apply=True, backup=backup)

    assert report["verdict"] == "STOP"
    assert report["drift"], "drift must be reported, not silently overwritten"
    assert db.read_bytes() == drifted, "a refused run must not write"


def test_apply_refuses_when_backup_is_not_the_target(tmp_path):
    records = _corrections()
    db = tmp_path / "copy.sqlite"
    _make_db(db, records)
    stale = tmp_path / "stale.sqlite"
    _make_db(stale, records)
    conn = sqlite3.connect(stale)
    conn.execute("INSERT INTO senses (sense_id, entry_id, gloss_en, gloss_ne)"
                 " VALUES (-2, -2, 'other', 'अरु')")
    conn.commit()
    conn.close()
    before = db.read_bytes()

    report = apply_mod.run(db, CORRECTIONS, apply=True, backup=stale)

    assert report["verdict"] == "STOP"
    assert any(c["name"] == "backup_matches_target" and not c["ok"] for c in report["checks"])
    assert db.read_bytes() == before


def test_allowlist_suppresses_only_the_exact_value(tmp_path):
    db = tmp_path / "enc.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE senses (sense_id INTEGER PRIMARY KEY, gloss_ne TEXT)")
    conn.execute("INSERT INTO senses VALUES (1, 'सूची अक्षर C')")
    conn.execute("INSERT INTO senses VALUES (2, 'सूची अक्षर D')")
    conn.commit()
    conn.close()

    allow = [{"table": "senses", "column": "gloss_ne", "row": 1,
              "value": "सूची अक्षर C", "reason": "letter name"}]
    report = enc_mod.check_database(db, strict=True, allowlist=allow)

    assert [w["row"] for w in report["warnings"]] == [2], "the unmatched row must still warn"
    assert [a["row"] for a in report["allowed"]] == [1]
    assert report["ok"] is False

    full = allow + [{"table": "senses", "column": "gloss_ne", "row": 2,
                     "value": "सूची अक्षर D", "reason": "letter name"}]
    assert enc_mod.check_database(db, strict=True, allowlist=full)["ok"] is True


def test_allowlist_cannot_hide_an_error(tmp_path):
    db = tmp_path / "enc.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE senses (sense_id INTEGER PRIMARY KEY, gloss_ne TEXT)")
    conn.execute("INSERT INTO senses VALUES (1, 'किताब\ufffd')")
    conn.commit()
    conn.close()

    allow = [{"table": "senses", "column": "gloss_ne", "row": 1,
              "value": "किताब\ufffd", "reason": "attempted override"}]
    report = enc_mod.check_database(db, strict=False, allowlist=allow)

    assert report["ok"] is False
    assert report["errors"], "an error must never be allowlisted"


def test_store_sync_updates_only_the_recorded_rows(tmp_path):
    records = [r for r in _corrections() if r["table"] == "senses"]
    store = tmp_path / "translations.db"
    conn = sqlite3.connect(store)
    conn.execute("CREATE TABLE translations (translation_id INTEGER PRIMARY KEY,"
                 " origin_source TEXT, origin_record_id TEXT, text TEXT, publication_status TEXT)")
    for i, rec in enumerate(records, start=1):
        conn.execute("INSERT INTO translations VALUES (?, 'dictionary.sqlite:senses.ne', ?, ?,"
                     " 'labeled')", (i, str(rec["key_value"]), rec["old"]))
    conn.execute("INSERT INTO translations VALUES (?, 'dictionary.sqlite:senses.ne', '999',"
                 " 'अछुत', 'labeled')", (len(records) + 1,))
    conn.commit()
    conn.close()
    backup = tmp_path / "store-before.sqlite"
    backup.write_bytes(store.read_bytes())

    report = sync_mod.run(store, CORRECTIONS, apply=True, backup=backup)

    assert report["verdict"] == "APPLIED", report
    assert report["changed_rows"] == len(records)
    conn = sqlite3.connect(store)
    got = {r[0]: r[1] for r in conn.execute("SELECT origin_record_id, text FROM translations")}
    conn.close()
    for rec in records:
        assert got[str(rec["key_value"])] == rec["new"]
    assert got["999"] == "अछुत"


def test_store_sync_refuses_when_the_copy_drifted(tmp_path):
    records = [r for r in _corrections() if r["table"] == "senses"]
    store = tmp_path / "translations.db"
    conn = sqlite3.connect(store)
    conn.execute("CREATE TABLE translations (translation_id INTEGER PRIMARY KEY,"
                 " origin_source TEXT, origin_record_id TEXT, text TEXT, publication_status TEXT)")
    for i, rec in enumerate(records, start=1):
        text = "बदलियो" if i == 1 else rec["old"]
        conn.execute("INSERT INTO translations VALUES (?, 'dictionary.sqlite:senses.ne', ?, ?,"
                     " 'labeled')", (i, str(rec["key_value"]), text))
    conn.commit()
    conn.close()
    before = store.read_bytes()
    backup = tmp_path / "store-before.sqlite"
    backup.write_bytes(before)

    report = sync_mod.run(store, CORRECTIONS, apply=True, backup=backup)

    assert report["verdict"] == "STOP"
    assert report["drift"]
    assert store.read_bytes() == before


@pytest.mark.skipif(not PRODUCTION.exists(), reason="production dictionary not present")
def test_production_dry_run_has_no_drift():
    report = apply_mod.run(PRODUCTION, CORRECTIONS, apply=False, backup=None)
    assert report["verdict"] == "DRY-RUN-OK", report["drift"]


@pytest.mark.skipif(not PRODUCTION.exists(), reason="production dictionary not present")
def test_production_encoding_gate_is_clean_in_strict_mode():
    allow = enc_mod._load_allowlist(ALLOWLIST)
    report = enc_mod.check_database(PRODUCTION, strict=True, allowlist=allow)
    assert report["errors"] == [], report["errors"]
    assert report["warnings"] == [], report["warnings"]


@pytest.mark.skipif(not PRODUCTION.exists(), reason="production dictionary not present")
def test_production_allowlist_values_still_match():
    with open(ALLOWLIST, encoding="utf-8") as fh:
        entries = json.load(fh)["entries"]
    conn = sqlite3.connect("file:%s?mode=ro" % PRODUCTION.as_posix(), uri=True)
    for entry in entries:
        row = conn.execute('SELECT "%s" FROM "%s" WHERE rowid = ?'
                           % (entry["column"], entry["table"]), (entry["row"],)).fetchone()
        if row is None:  # the allowlist uses the integer primary key, not rowid
            row = conn.execute('SELECT "%s" FROM "%s" WHERE "%s_id" = ?'
                               % (entry["column"], entry["table"], entry["table"].rstrip("s")),
                               (entry["row"],)).fetchone()
        assert row and row[0] == entry["value"], entry
    conn.close()
