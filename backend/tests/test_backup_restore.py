"""Backup / restore test (Phase 10).

A backup is only real if a restore of it is verified. These tests use small
synthetic databases so the suite stays fast; the same code path is used against
the real 121 MB file by `python tools/backup_db.py --verify <file>`.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tools import backup_db  # noqa: E402


def _make_db(path: Path, gloss: str) -> Path:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE entries (entry_id INTEGER PRIMARY KEY, simplified TEXT);
        CREATE TABLE senses (sense_id INTEGER PRIMARY KEY, entry_id INTEGER,
                             gloss_en TEXT);
        INSERT INTO entries VALUES (1, '水');
        INSERT INTO senses VALUES (1, 1, 'x');
        """
    )
    con.execute("UPDATE senses SET gloss_en=?", (gloss,))
    con.commit()
    con.close()
    return path


def test_restore_of_identical_copy_passes(tmp_path, monkeypatch):
    live = _make_db(tmp_path / "live.sqlite", "water")
    monkeypatch.setattr(backup_db, "WORKING_DB", live)
    monkeypatch.setattr(backup_db, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(backup_db, "TABLES_FOR_DIGEST", ["entries", "senses"])

    import shutil
    copy = tmp_path / "backup.sqlite"
    shutil.copy2(live, copy)
    assert backup_db.verify(copy) is True


def test_restore_detects_one_edited_cell(tmp_path, monkeypatch):
    live = _make_db(tmp_path / "live.sqlite", "water")
    monkeypatch.setattr(backup_db, "WORKING_DB", live)
    monkeypatch.setattr(backup_db, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(backup_db, "TABLES_FOR_DIGEST", ["entries", "senses"])

    import shutil
    copy = tmp_path / "backup.sqlite"
    shutil.copy2(live, copy)
    # Same row count, different content: the case a count check would miss.
    con = sqlite3.connect(copy)
    con.execute("UPDATE senses SET gloss_en='water!'")
    con.commit()
    con.close()
    assert backup_db.verify(copy) is False


def test_backup_writes_checksum_sidecar(tmp_path, monkeypatch, capsys):
    live = _make_db(tmp_path / "live.sqlite", "water")
    monkeypatch.setattr(backup_db, "WORKING_DB", live)
    monkeypatch.setattr(backup_db, "BACKUP_DIR", tmp_path)
    target = backup_db.backup()
    sidecar = target.with_suffix(target.suffix + ".sha256")
    assert sidecar.exists()
    digest, name = sidecar.read_text(encoding="utf-8").split("  ")
    assert name.strip() == target.name
    assert digest == backup_db.sha256_file(target)
