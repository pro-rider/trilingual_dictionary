"""Golden-vector parity for the resolution policy, plus a real-data integration
check against a copy of the production dictionary and governance store."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3

import pytest

from app.translations import resolve, schema, status

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN = os.path.join(HERE, "shared", "translation_resolution_golden.json")
DICTIONARY = os.path.join(HERE, "backend", "data", "build", "dictionary.sqlite")
STORE = os.path.join(HERE, "backend", "data", "build", "translations.db")


def _golden():
    with open(GOLDEN, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("case", _golden(), ids=[c["name"] for c in _golden()])
def test_resolution_matches_golden(case):
    gov = dict(case["governance"] or {})
    got = resolve.resolve(case["dictionary"], gov or None)
    assert got["text"] == case["expected"]["text"]
    assert got["source"] == case["expected"]["source"]
    assert got["status"] == case["expected"]["status"]
    assert got["visible"] == case["expected"]["visible"]


def test_an_import_copy_does_not_become_a_second_meaning():
    got = resolve.resolve(
        "पानी",
        {"text": "पानी", "generation_method": "llm", "validation_status": "incomplete",
         "publication_status": "labeled", "origin_source": "dictionary.sqlite:senses.ne"},
    )
    assert (got["text"], got["source"], got["status"]) == ("पानी", "dictionary", "ai_unverified")


@pytest.mark.skipif(not (os.path.exists(DICTIONARY) and os.path.exists(STORE)),
                    reason="production dictionary/store not present")
def test_real_data_one_nepali_line_per_sense(tmp_path):
    """Every one of the 3,245 imported senses resolves to exactly one line."""
    store = str(tmp_path / "translations.db")
    shutil.copy2(STORE, store)

    conn = schema.connect(store)
    gov = {}
    for sid, sklearn, entry_key, text, method, strength, validation, publication, \
            verification, origin, language, match, supersedes in conn.execute(
            "select origin_record_id, sense_key, entry_key, text, generation_method, "
            "evidence_strength, validation_status, publication_status, human_verification, "
            "origin_source, evidence_language, sense_match_method, supersedes_id "
            "from translations where origin_source='dictionary.sqlite:senses.ne'"):
        gov[sid] = {"text": text, "generation_method": method, "evidence_strength": strength,
                    "validation_status": validation, "publication_status": publication,
                    "human_verification": verification, "origin_source": origin,
                    "evidence_language": language, "sense_match_method": match}
    # A sense is retired when another row points at its translation_id.
    superseded = {r[0] for r in conn.execute(
        "select supersedes_id from translations where supersedes_id is not null")}
    conn.close()
    assert len(gov) == 3245
    assert not superseded

    d = sqlite3.connect("file:%s?mode=ro" % DICTIONARY.replace("\\", "/"), uri=True)
    pairs = []
    for sense_id, ne in d.execute("select sense_id, gloss_ne from senses "
                                  "where trim(coalesce(gloss_ne,''))<>''"):
        pairs.append((str(sense_id), (ne or "").strip()))
    d.close()
    assert len(pairs) == 3245

    sources = {"dictionary": 0, "governance": 0, "none": 0}
    for sid, dict_text in pairs:
        got = resolve.resolve(dict_text, gov[sid])
        assert got["text"] == dict_text, sid                 # exactly the original
        assert got["visible"] is True, sid
        assert got["status"] == "ai_unverified", sid
        sources[got["source"]] += 1
    assert sources == {"dictionary": 3245, "governance": 0, "none": 0}


@pytest.mark.skipif(not os.path.exists(STORE), reason="production store not present")
def test_real_store_has_no_verified_or_supported_legacy_rows():
    conn = schema.connect(STORE)
    row = conn.execute(
        "select count(*), sum(human_verification='verified'), "
        "       sum(validation_status='passed'), sum(evidence_strength<>'none'), "
        "       sum(publication_status<>'labeled') "
        "from translations where origin_source='dictionary.sqlite:senses.ne'").fetchone()
    derived = [status.derive({"text": "x", "generation_method": m, "evidence_strength": s,
                              "validation_status": v, "publication_status": p,
                              "human_verification": h})["code"]
               for m, s, v, p, h in conn.execute(
                   "select distinct generation_method, evidence_strength, validation_status, "
                   "publication_status, human_verification from translations "
                   "where origin_source='dictionary.sqlite:senses.ne'")]
    conn.close()
    assert row == (3245, 0, 0, 0, 0)
    assert derived == ["ai_unverified"]
