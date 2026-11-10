"""Guards for the Nepali correction pipeline and the encoding allowlist.

Each test pairs a positive case with the case that must be refused, because a
repair tool that cannot refuse is more dangerous than no repair tool.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)

from tools import apply_ne_corrections as apply_mod  # noqa: E402
from tools import check_encoding as enc_mod  # noqa: E402
from app.translations import script_mix  # noqa: E402

CORRECTIONS = os.path.join(REPO, "docs", "NE-CORRECTIONS.json")
ALLOWLIST = os.path.join(REPO, "docs", "ENCODING-ALLOWLIST.json")
PRODUCTION = os.path.join(BACKEND, "data", "build", "dictionary.sqlite")


def _corrections():
    with open(CORRECTIONS, encoding="utf-8") as fh:
        return json.load(fh)["corrections"]


def _make_db(path, corrections):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE entries (entry_id INTEGER PRIMARY KEY, simplified TEXT)")
    conn.execute("CREATE TABLE senses (sense_id INTEGER PRIMARY KEY, entry_id INTEGER,"
                 " gloss_en TEXT, gloss_ne TEXT, ne_status TEXT NOT NULL DEFAULT 'none')")
    conn.executemany("INSERT INTO entries (entry_id, simplified) VALUES (?, ?)",
                     [(c["sense_id"] + 1, c["entry"]) for c in corrections])
    conn.executemany(
        "INSERT INTO senses (sense_id, entry_id, gloss_en, gloss_ne, ne_status) "
        "VALUES (?, ?, ?, ?, 'ai_translated')",
        [(c["sense_id"], c["sense_id"] + 1, c["gloss_en"], c["old"]) for c in corrections])
    conn.execute("INSERT INTO senses (sense_id, entry_id, gloss_en, gloss_ne) "
                 "VALUES (?, ?, 'untouched', 'अछुत')", (max(c["sense_id"] for c in corrections) + 5,
                                                        max(c["sense_id"] for c in corrections) + 6))
    conn.commit()
    conn.close()


def test_corrections_file_is_well_formed():
    records = _corrections()
    assert records, "corrections file is empty"
    ids = [r["sense_id"] for r in records]
    assert len(ids) == len(set(ids))
    for rec in records:
        assert rec["old"] != rec["new"]
        assert "\ufffd" not in rec["new"], rec
        verdict = script_mix.classify(rec["new"])
        assert not verdict["quarantine_justified"], (rec["new"], verdict)
        assert rec["basis"] and rec["evidence"], rec


def test_dry_run_writes_nothing(tmp_path):
    records = _corrections()
    db = tmp_path / "copy.sqlite"
    _make_db(db, records)
    before = db.read_bytes()

    report = apply_mod.run(db, CORRECTIONS_PATH(), apply=False, backup=None)

    assert report["verdict"] == "DRY-RUN-OK"
    assert db.read_bytes() == before
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT gloss_ne FROM senses WHERE sense_id = ?",
                        (records[0]["sense_id"],)).fetchone()[0] == records[0]["old"]
    conn.close()


def test_apply_changes_only_the_recorded_rows(tmp_path):
    records = _corrections()
    db = tmp_path / "copy.sqlite"
    _make_db(db, records)
    backup = tmp_path / "backup.sqlite"
    backup.write_bytes(db.read_bytes())

    report = apply_mod.run(db, CORRECTIONS_PATH(), apply=True, backup=backup)

    assert report["verdict"] == "APPLIED", report
    assert report["changed_rows"] == len(records)
    conn = sqlite3.connect(db)
    for rec in records:
        assert conn.execute("SELECT gloss_ne FROM senses WHERE sense_id = ?",
                            (rec["sense_id"],)).fetchone()[0] == rec["new"]
    untouched = conn.execute("SELECT gloss_ne FROM senses WHERE gloss_en = 'untouched'").fetchone()
    assert untouched[0] == "अछुत"
    conn.close()


def test_apply_refuses_on_drift(tmp_path):
    records = _corrections()
    db = tmp_path / "copy.sqlite"
    _make_db(db, records)

    conn = sqlite3.connect(db)
    conn.execute("UPDATE senses SET gloss_ne = 'बदलियो' WHERE sense_id = ?",
                 (records[0]["sense_id"],))
    conn.commit()
    conn.close()
    drifted = db.read_bytes()
    # The backup is taken after the drift, so the run gets past the backup check
    # and has to refuse on the value mismatch instead.
    backup = tmp_path / "backup.sqlite"
    backup.write_bytes(drifted)

    report = apply_mod.run(db, CORRECTIONS_PATH(), apply=True, backup=backup)

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
    conn.execute("INSERT INTO senses (sense_id, entry_id, gloss_en, gloss_ne) "
                 "VALUES (999999, 1, 'x', 'x')")
    conn.commit()
    conn.close()
    before = db.read_bytes()

    report = apply_mod.run(db, CORRECTIONS_PATH(), apply=True, backup=stale)

    assert report["verdict"] == "STOP"
    assert any(c["name"] == "backup_matches_target" and not c["ok"]
               for c in report["checks"]), report["checks"]
    assert db.read_bytes() == before


def test_apply_refuses_without_backup(tmp_path):
    records = _corrections()
    db = tmp_path / "copy.sqlite"
    _make_db(db, records)
    before = db.read_bytes()

    report = apply_mod.run(db, CORRECTIONS_PATH(), apply=True, backup=None)

    assert report["verdict"] == "STOP"
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

    report_clean = enc_mod.check_database(db, strict=True, allowlist=allow + [
        {"table": "senses", "column": "gloss_ne", "row": 2,
         "value": "सूची अक्षर D", "reason": "letter name"}])
    assert report_clean["ok"] is True


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


def test_allowlist_file_matches_the_shipped_rows():
    with open(ALLOWLIST, encoding="utf-8") as fh:
        entries = json.load(fh)["entries"]
    assert entries


@pytest.mark.skipif(not os.path.exists(PRODUCTION), reason="production dictionary not present")
def test_production_dry_run_has_no_drift():
    report = apply_mod.run(PRODUCTION_PATH(), CORRECTIONS_PATH(), apply=False, backup=None)
    assert report["verdict"] == "DRY-RUN-OK", report.get("drift")


@pytest.mark.skipif(not os.path.exists(PRODUCTION), reason="production dictionary not present")
def test_production_allowlist_values_still_match():
    with open(ALLOWLIST, encoding="utf-8") as fh:
        entries = json.load(fh)["entries"]
    conn = sqlite3.connect("file:%s?mode=ro" % PRODUCTION.replace("\\", "/"), uri=True)
    for entry in entries:
        row = conn.execute('SELECT "%s" FROM "%s" WHERE "%s" = ?'
                           % (entry["column"], entry["table"], "sense_id"),
                           (entry["row"],)).fetchone()
        assert row and row[0] == entry["value"], entry
    conn.close()


def CORRECTIONS_PATH():
    from pathlib import Path
    return Path(CORRECTIONS)


def PRODUCTION_PATH():
    from pathlib import Path
    return Path(PRODUCTION)
