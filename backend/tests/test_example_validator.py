"""Phase 5 gate: a generated sentence may only land in the candidate table.

Two promises are tested here, neither needs a provider:

* `validate()` rejects the four things the brief names — wrong headword, wrong
  language, silly length, offensive content;
* the generator writes `example_candidates` with `status='pending_review'` and
  never touches `examples`, so no generated sentence can bypass review.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BACKEND, "tools"))

import gen_example_sentences as gen  # noqa: E402

DB = os.path.join(BACKEND, "data", "build", "dictionary.sqlite")


@pytest.mark.parametrize("headword,zh,en,ne,reason", [
    ("椅子", "这是一把皮革的椅子", "This is a leather chair.", "यो एक चमडेको कुर्सी हो", None),
    ("椅子", "这是一把皮革的桌子", "This is a leather table.", "यो एक चमडेको टेबल हो",
     "headword_missing_from_chinese"),
    ("椅子", "椅子短", "This is a leather chair.", "यो एक चमडेको कुर्सी हो", "chinese_length"),
    ("椅子", "这是一把皮革的椅子", "This is 椅子 chair.", "यो एक चमडेको कुर्सी हो",
     "chinese_inside_english"),
    ("椅子", "这是一把皮革的椅子", "This is a leather chair.", "yo ek chamadeko kursi ho",
     "nepali_not_devanagari"),
    ("椅子", "这是一把皮革的椅子", "", "यो एक चमडेको कुर्सी हो", "empty_field"),
    ("椅子", "这是一把皮革的椅子 kill", "This is a leather chair.", "यो एक चमडेको कुर्सी हो",
     "blocked_content:kill"),
])
def test_validator_rules(headword, zh, en, ne, reason):
    assert gen.validate(headword, zh, en, ne) == reason


@pytest.mark.skipif(
    not os.path.exists(DB), reason="built dictionary database not present"
)
def test_generated_rows_go_to_candidates_only(tmp_path):
    copy = tmp_path / "copy.sqlite"
    shutil.copy2(DB, copy)

    items = []
    con = sqlite3.connect(copy)
    # The production database already holds a couple of reviewed candidates
    # from an earlier run; clear them so the assertion below measures only what
    # this run persisted.
    con.executescript(gen.DDL)
    con.execute("DELETE FROM example_candidates")
    con.commit()
    rows = con.execute(
        """
        SELECT s.sense_id, e.simplified FROM senses s JOIN entries e USING(entry_id)
        JOIN launch_set l USING(entry_id)
        WHERE l.tier<=2 AND s.sense_id NOT IN (SELECT sense_id FROM examples)
        ORDER BY l.tier, e.freq_rank, s.sense_id LIMIT 2
        """
    ).fetchall()
    con.close()
    headwords = [row[1] for row in rows]

    def fake_call(cfg, payload_items, model, max_tokens=1600):
        return [{"sid": item["sid"], "zh": f"我学过{item['w']}这个字",
                 "en": f"I have learned the character {item['w']}.",
                 "ne": f"मैले {item['w']} अक्षर सिकें।"}
                for item in payload_items]

    gen.call_openrouter = fake_call
    gen.main(["--limit", "2", "--batch", "2", "--db", str(copy), "--sleep", "0"])

    con = sqlite3.connect(copy)
    con.executescript(gen.DDL)
    stored = con.execute(
        "SELECT sense_id, status FROM example_candidates ORDER BY sense_id"
    ).fetchall()
    assert len(stored) == 2, "the generator must persist its sentences"
    assert all(status == "pending_review" for _sid, status in stored)
    assert con.execute("SELECT count(*) FROM example_candidates WHERE sense_id IN "
                       "(SELECT sense_id FROM examples)").fetchone()[0] == 0
    # ...and the published table is untouched.
    assert con.execute("SELECT count(*) FROM examples").fetchone()[0] == 392
    con.close()
