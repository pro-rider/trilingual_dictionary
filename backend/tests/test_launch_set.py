"""Guards on the launch set: it must exist, be complete, and be reproducible."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

import build_launch_set  # noqa: E402

DB = os.path.join(BACKEND, "data", "build", "dictionary.sqlite")

# The built dictionary is a 122 MB artifact and is not committed, so a clean
# checkout (CI included) has no database to read. Skipping keeps the gate
# honest about what it can and cannot observe without that artifact.
pytestmark = pytest.mark.skipif(
    not os.path.exists(DB), reason="built dictionary database not present"
)


def _con():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def test_launch_set_covers_every_entry_once():
    con = _con()
    total = con.execute("SELECT count(*) FROM launch_set").fetchone()[0]
    db_total = con.execute("SELECT count(*) FROM entries").fetchone()[0]
    assert total == db_total
    assert con.execute(
        "SELECT count(*) FROM (SELECT entry_id FROM launch_set "
        "GROUP BY entry_id HAVING count(*) > 1)"
    ).fetchone()[0] == 0


def test_tier1_is_exactly_the_hsk_set():
    con = _con()
    hsk = con.execute(
        "SELECT count(*) FROM entries WHERE hsk_level IS NOT NULL"
    ).fetchone()[0]
    tier1 = con.execute("SELECT count(*) FROM launch_set WHERE tier=1").fetchone()[0]
    assert tier1 == hsk
    # Negative control: no HSK entry may sit outside tier 1.
    assert con.execute(
        "SELECT count(*) FROM entries e JOIN launch_set l USING(entry_id) "
        "WHERE e.hsk_level IS NOT NULL AND l.tier != 1"
    ).fetchone()[0] == 0


def test_launch_tiers_are_bounded():
    con = _con()
    tiers12 = con.execute(
        "SELECT count(*) FROM launch_set WHERE tier <= 2"
    ).fetchone()[0]
    assert tiers12 == 5000


def test_digest_is_reproducible():
    con = _con()
    digest = hashlib.sha256(
        "\n".join(
            f"{eid}:{tier}"
            for eid, tier in con.execute(
                "SELECT entry_id, tier FROM launch_set ORDER BY entry_id"
            )
        ).encode("utf-8")
    ).hexdigest()
    assert digest == build_launch_set.report(_con())["digest"]
