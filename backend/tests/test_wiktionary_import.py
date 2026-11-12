"""Guards on the Chinese-definition import: provenance, no wiki junk, no repeats."""
from __future__ import annotations

import os
import sqlite3

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BACKEND, "data", "build", "dictionary.sqlite")


def _con():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def test_every_provenance_row_has_a_gloss():
    con = _con()
    orphans = con.execute(
        "SELECT count(*) FROM gloss_provenance p JOIN senses s USING(sense_id) "
        "WHERE s.gloss_zh IS NULL OR trim(s.gloss_zh)=''"
    ).fetchone()[0]
    assert orphans == 0


def test_imported_glosses_carry_no_wiki_syntax():
    con = _con()
    bad = con.execute(
        "SELECT count(*) FROM gloss_provenance p JOIN senses s USING(sense_id) "
        "WHERE s.gloss_zh LIKE '%{{%' OR s.gloss_zh LIKE '%[[]%' "
        "OR s.gloss_zh LIKE '%ref=%' OR s.gloss_zh LIKE '%|%'"
    ).fetchone()[0]
    assert bad == 0


def test_no_gloss_is_just_the_headword():
    """A repeated headword is the bug this release is fixing, not a definition."""
    con = _con()
    bad = con.execute(
        "SELECT count(*) FROM senses s JOIN entries e USING(entry_id) "
        "WHERE trim(s.gloss_zh) = trim(e.simplified) "
        "OR trim(s.gloss_zh) = trim(e.traditional)"
    ).fetchone()[0]
    assert bad == 0


def test_high_frequency_entries_were_not_auto_imported():
    """The top-10k window stays for human review, by decision (A4)."""
    con = _con()
    bad = con.execute(
        "SELECT count(*) FROM gloss_provenance p JOIN entries e USING(entry_id) "
        "WHERE e.freq_rank IS NOT NULL AND e.freq_rank <= 10000"
    ).fetchone()[0]
    assert bad == 0


def test_no_xinhua_or_moedic_sourced_rows_in_senses():
    con = _con()
    sources = {
        row[0]
        for row in con.execute("SELECT DISTINCT source FROM gloss_provenance")
    }
    assert sources <= {"zh.wiktionary"}, sources
    licences = {
        row[0]
        for row in con.execute("SELECT DISTINCT license FROM gloss_provenance")
    }
    assert all("ND" not in (lic or "") for lic in licences), licences
