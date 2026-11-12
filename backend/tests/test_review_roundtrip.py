"""Round-trip proof for the review packages.

Builds a tiny review workbook from real rows, runs `tools/import_review.py`
against a throwaway copy of the database, and checks that approve / edit /
delete each did exactly one thing — including that a blank decision does
nothing at all.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys

import pytest
from openpyxl import Workbook

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

import import_review  # noqa: E402

DB = os.path.join(BACKEND, "data", "build", "dictionary.sqlite")
HEADERS = import_review.REQUIRED_HEADERS


@pytest.fixture()
def working_copy(tmp_path):
    target = tmp_path / "copy.sqlite"
    shutil.copy2(DB, target)
    return target


def _three_nepali_rows(con):
    rows = con.execute(
        """
        SELECT s.entry_id, e.simplified, e.pinyin_marked, s.gloss_en, s.gloss_ne,
               COALESCE(s.gloss_zh,''), s.sense_id
        FROM senses s JOIN entries e USING(entry_id) JOIN launch_set l USING(entry_id)
        WHERE l.tier<=2 AND s.gloss_ne IS NOT NULL AND trim(s.gloss_ne)!=''
        ORDER BY s.sense_id LIMIT 4
        """
    ).fetchall()
    return rows


def _write_book(path, records):
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Review"
    sheet.append(HEADERS)
    for record in records:
        sheet.append([record.get(name, "") for name in HEADERS])
    wb.save(path)


def test_decisions_are_applied_exactly_once(working_copy, tmp_path):
    con = sqlite3.connect(working_copy)
    rows = _three_nepali_rows(con)
    assert len(rows) == 4, "need four reviewable rows for this test"

    records = []
    for i, row in enumerate(rows):
        entry_id, headword, pinyin, en, ne, zh, sense_id = row
        decision = ["approve", "edit", "delete", ""][i]
        records.append({
            "entry_id": entry_id, "headword": headword, "pinyin": pinyin,
            "English gloss": en, "Nepali (machine)": ne, "Chinese candidate": zh,
            "source": "test", "decision": decision,
            "edited_text": "सम्पादित पाठ" if decision == "edit" else "",
        })
    book = tmp_path / "nepali-launch-part-01.xlsx"
    _write_book(book, records)

    dry = import_review.process_file(con, book, dry_run=True, applied_by="test")
    assert dry["errors"] == []
    assert dry["decisions"] == {"approve": 1, "edit": 1, "delete": 1}
    # A dry run must not have written anything.
    before = con.execute("SELECT count(*) FROM review_audit").fetchone()[0]
    assert before == 0

    live = import_review.process_file(con, book, dry_run=False, applied_by="test")
    assert live["errors"] == []
    assert live["applied"] == 3

    sense_ids = [row[6] for row in rows]
    approved = con.execute(
        "SELECT gloss_ne, ne_status FROM senses WHERE sense_id=?", (sense_ids[0],)
    ).fetchone()
    assert approved[0] == rows[0][4]
    assert approved[1] == "reviewed"

    edited = con.execute(
        "SELECT gloss_ne, ne_status FROM senses WHERE sense_id=?", (sense_ids[1],)
    ).fetchone()
    assert edited[0] == "सम्पादित पाठ"
    assert edited[1] == "reviewed"

    deleted = con.execute(
        "SELECT gloss_ne, ne_status FROM senses WHERE sense_id=?", (sense_ids[2],)
    ).fetchone()
    assert (deleted[0] or "") == ""
    assert deleted[1] == "none"

    untouched = con.execute(
        "SELECT gloss_ne, ne_status FROM senses WHERE sense_id=?", (sense_ids[3],)
    ).fetchone()
    assert untouched[0] == rows[3][4], "a blank decision must not change the row"

    assert con.execute("SELECT count(*) FROM review_audit").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM review_rejected").fetchone()[0] == 1
    con.close()


def test_bad_decision_is_rejected_not_guessed(working_copy, tmp_path):
    con = sqlite3.connect(working_copy)
    row = _three_nepali_rows(con)[0]
    book = tmp_path / "nepali-launch-part-02.xlsx"
    _write_book(book, [{
        "entry_id": row[0], "headword": row[1], "pinyin": row[2],
        "English gloss": row[3], "Nepali (machine)": row[4],
        "Chinese candidate": row[5], "source": "test", "decision": "yes please",
    }])
    result = import_review.process_file(con, book, dry_run=True, applied_by="test")
    assert result["applied"] == 0
    assert any("not approve/edit/delete" in e for e in result["errors"])
    con.close()


def test_edit_without_text_is_an_error(working_copy, tmp_path):
    con = sqlite3.connect(working_copy)
    row = _three_nepali_rows(con)[1]
    book = tmp_path / "nepali-launch-part-03.xlsx"
    _write_book(book, [{
        "entry_id": row[0], "headword": row[1], "pinyin": row[2],
        "English gloss": row[3], "Nepali (machine)": row[4],
        "Chinese candidate": row[5], "source": "test", "decision": "edit",
        "edited_text": "   ",
    }])
    result = import_review.process_file(con, book, dry_run=True, applied_by="test")
    assert result["applied"] == 0
    assert any("edited_text empty" in e for e in result["errors"])
    con.close()
