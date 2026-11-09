"""TASK 015 — pin capture and consistent copy, on fixture databases only."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from translation_agent.config import ProductionDatabaseRefused

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from capture_pins import capture_pins  # noqa: E402
from safe_copy import safe_copy  # noqa: E402


def make_db(path: Path, journal_mode: str = "delete") -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute(f"PRAGMA journal_mode={journal_mode}")
    conn.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, gloss TEXT)")
    conn.executemany(
        "INSERT INTO items (gloss) VALUES (?)",
        [("पानी",), ("किताब",), ("घर",)],
    )
    conn.execute("PRAGMA user_version=4")
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def fixture_db(tmp_path: Path) -> Path:
    return make_db(tmp_path / "fixture.db")


def test_pins_are_stable_across_runs(fixture_db: Path):
    a = capture_pins(str(fixture_db))
    b = capture_pins(str(fixture_db))
    for key in ("sha256", "bytes", "user_version", "schema_sha256", "tables"):
        assert a[key] == b[key], key


def test_pin_changes_when_one_row_changes(fixture_db: Path):
    before = capture_pins(str(fixture_db))
    conn = sqlite3.connect(str(fixture_db))
    conn.execute("INSERT INTO items (gloss) VALUES ('समय')")
    conn.commit()
    conn.close()
    after = capture_pins(str(fixture_db))
    assert after["sha256"] != before["sha256"]
    assert after["tables"]["items"] == before["tables"]["items"] + 1


def test_pin_capture_writes_nothing(fixture_db: Path):
    directory = fixture_db.parent
    before = sorted(p.name for p in directory.iterdir())
    capture_pins(str(fixture_db))
    after = sorted(p.name for p in directory.iterdir())
    assert before == after, f"pin capture created files: {set(after) - set(before)}"


def test_copy_is_consistent_and_source_is_untouched(fixture_db: Path, tmp_path: Path):
    report = safe_copy(str(fixture_db), str(tmp_path / "copy.db"))
    assert report["integrity_check"] == "ok"
    assert report["copy_pin"]["tables"] == report["source_pin_before"]["tables"]
    assert report["source_pin_before"]["sha256"] == report["source_pin_after"]["sha256"]

    conn = sqlite3.connect(report["destination"])
    rows = conn.execute("SELECT gloss FROM items ORDER BY id").fetchall()
    conn.close()
    assert rows == [("पानी",), ("किताब",), ("घर",)]


def test_copy_of_wal_database_is_consistent(tmp_path: Path):
    source = make_db(tmp_path / "wal.db", journal_mode="WAL")
    report = safe_copy(str(source), str(tmp_path / "wal_copy.db"))
    assert report["integrity_check"] == "ok"
    assert report["copy_pin"]["tables"] == report["source_pin_before"]["tables"]
    assert report["copy_pin"]["sha256"]  # a real copy exists


def test_destination_that_is_the_source_is_refused(fixture_db: Path):
    with pytest.raises(ValueError):
        safe_copy(str(fixture_db), str(fixture_db))


def test_protected_destination_is_refused(tmp_path: Path):
    source = make_db(tmp_path / "src.db")
    protected = tmp_path / "backend" / "data" / "build" / "translations.db"
    protected.parent.mkdir(parents=True)
    with pytest.raises(ProductionDatabaseRefused):
        safe_copy(str(source), str(protected))


def test_pin_of_missing_file_fails_loudly(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        capture_pins(str(tmp_path / "absent.db"))
