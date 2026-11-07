"""English->Chinese lookup ranking.

The dictionary has ~198k senses, so a naive "shortest matching gloss" rule
answers "arrange" with 布局 (gloss: "arrangement") instead of 安排
(gloss: "to arrange"), and "raisin" with a Go term. These tests build a small
database with the production schema and assert the ranking rules directly.
"""

import sqlite3

import pytest

from app.core import config
from app.services import sqlite_dataset as sd
from tools.build_dictionary import SCHEMA


@pytest.fixture()
def mini_db(tmp_path, monkeypatch):
    path = tmp_path / "dictionary.sqlite"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    rows = [
        # entry_id, simplified, traditional, pinyin_num, pinyin_marked,
        # pinyin_plain, category, is_proper, hsk_level
        (1, "布局", "布局", "bu4ju2", "bùjú", "buju", "word", 0, None),
        (2, "安排", "安排", "an1pai2", "ānpái", "anpai", "word", 0, 5),
        (3, "摆", "擺", "bai3", "bǎi", "bai", "word", 0, 5),
        (4, "葡萄干", "葡萄乾", "pu2tao5gan1", "pútáogān", "putaogan", "word", 0, None),
        (5, "提子", "提子", "ti2zi5", "tízi", "tizi", "word", 0, None),
        (6, "花园", "花園", "hua1yuan2", "huāyuán", "huayuan", "word", 0, None),
    ]
    for r in rows:
        con.execute(
            "INSERT INTO entries (entry_id, simplified, traditional, pinyin_num,"
            " pinyin_marked, pinyin_plain, category, pos_primary,"
            " is_proper, is_chengyu, is_classifier, rarity, freq_rank, hsk_level,"
            " status) VALUES (?,?,?,?,?,?, 'word', '', ?, 0, 0, 0, NULL, ?, 'active')",
            (r[0], r[1], r[2], r[3], r[4], r[5], r[7], r[8]),
        )
    senses = [
        (1, 0, "arrangement"),          # 布局
        (2, 0, "to arrange"),           # 安排
        (3, 0, "to arrange"),           # 摆
        (4, 0, "raisin"),               # 葡萄干
        (5, 0, "to capture stones (in Go)"),  # 提子
        (6, 0, "garden"),               # 花园
    ]
    for sense_id, (entry_id, sense_order, gloss) in enumerate(senses, start=101):
        con.execute(
            "INSERT INTO senses (sense_id, entry_id, sense_order, gloss_en,"
            " gloss_zh, gloss_ne, ne_status, source_id) VALUES (?,?,?,?,NULL,NULL,"
            "'pending', 1)",
            (sense_id, entry_id, sense_order, gloss),
        )
    con.execute(
        "INSERT INTO senses (sense_id, entry_id, sense_order, gloss_en, gloss_zh,"
        " gloss_ne, ne_status, source_id) VALUES (301, 2, 1, 'arrangements',"
        " NULL, NULL, 'pending', 1)"
    )
    con.commit()
    con.close()

    monkeypatch.setattr(config.settings, "dictionary_db_path", str(path))
    sd.reset_cache()
    yield path
    sd.reset_cache()


def test_prefers_primary_sense_match_over_substring(mini_db):
    entry = sd.find_entry("arrange", "en")
    assert entry is not None
    # Must NOT land on 布局, which only matches "arrangement" as a substring.
    assert entry["word_zh"] != "布局"
    assert entry["senses"][0]["meaning_en"].lower().startswith("to arrange")


def test_exact_gloss_beats_go_term(mini_db):
    entry = sd.find_entry("raisin", "en")
    assert entry is not None
    assert entry["word_zh"] == "葡萄干"
    assert entry["senses"][0]["meaning_en"] == "raisin"


def test_english_lookup_returns_nepali_when_present(mini_db):
    import sqlite3 as _s

    con = _s.connect(mini_db)
    con.execute("UPDATE senses SET gloss_ne = 'व्यवस्था गर्नु' WHERE entry_id IN (2, 3)")
    con.commit()
    con.close()

    entry = sd.find_entry("arrange", "en")
    assert entry["senses"][0]["meaning_ne"] == "व्यवस्था गर्नु"
