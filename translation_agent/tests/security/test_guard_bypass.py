"""TASK 013 — can the production-database guard be bypassed?

Method: the real production files are never opened.  A temporary file is
designated "protected" by giving it the production name and living under the
production path markers, then every path variant is pointed at it.

Bypasses are recorded as ``xfail(strict=True)`` tests: they assert refusal,
they fail, and the failure *is* the report.  Nothing here fixes the guard.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from translation_agent.config import (
    AgentConfig,
    ProductionDatabaseRefused,
    assert_not_production,
    manifest_coverage,
)


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture()
def protected(repo_root: Path) -> Path:
    """A temp file that stands in for the production database."""
    target = repo_root / "backend" / "data" / "build" / "translations.db"
    target.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(target))
    conn.execute("create table t(x)")
    conn.commit()
    conn.close()
    return target


def refused(path: str) -> bool:
    return refused_with(path, None)


def refused_with(path: Path | str, manifest: Path | str | None) -> bool:
    try:
        assert_not_production(str(path), str(manifest) if manifest else None)
    except ProductionDatabaseRefused:
        return True
    return False


# ---------------------------------------------------------------- refusals
def test_absolute_path_is_refused(protected: Path):
    assert refused(str(protected))


def test_relative_path_is_refused(protected: Path, repo_root: Path, monkeypatch):
    monkeypatch.chdir(repo_root)
    assert refused("backend/data/build/translations.db")


def test_dot_and_dotdot_segments_are_refused(protected: Path, repo_root: Path, monkeypatch):
    monkeypatch.chdir(repo_root)
    assert refused("./backend/./data/build/translations.db")
    assert refused("backend/../backend/data/build/translations.db")


def test_symlink_to_protected_is_refused(protected: Path, tmp_path: Path):
    link = tmp_path / "harmless.db"
    try:
        os.symlink(protected, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    assert refused(str(link))


def test_mixed_separators_are_refused(protected: Path):
    # Windows-style separators on a POSIX host.
    messy = str(protected).replace("/", "\\")
    assert refused(messy)


def test_uppercase_name_is_refused(repo_root: Path):
    upper = repo_root / "backend" / "data" / "build" / "TRANSLATIONS.DB"
    upper.parent.mkdir(parents=True)
    upper.write_bytes(b"")
    assert refused(str(upper))


def test_differently_named_parent_is_refused(tmp_path: Path):
    # Same filename, totally unrelated directory: still refused by name.
    other = tmp_path / "unrelated" / "translations.db"
    other.parent.mkdir()
    other.write_bytes(b"")
    assert refused(str(other))


def test_env_override_cannot_point_at_production(protected: Path, monkeypatch):
    monkeypatch.setenv("TRANSLATION_AGENT_LEDGER", str(protected))
    with pytest.raises(ProductionDatabaseRefused):
        AgentConfig.from_env().validate()


def test_unrelated_database_is_allowed(tmp_path: Path):
    safe = tmp_path / "safe" / "candidates.db"
    safe.parent.mkdir()
    assert not refused(str(safe))


# ------------------------------------------------- previously bypassable
# These three defeated the old name-only guard.  They must now be refused by
# the ambiguity rules and the identity manifest, not by luck.
@pytest.fixture()
def protected_plain(tmp_path: Path) -> Path:
    """A protected file WITHOUT production path markers, so only identity protects it."""
    vault = tmp_path / "plainvault"
    vault.mkdir()
    target = vault / "translations.db"
    conn = sqlite3.connect(str(target))
    conn.execute("create table t(x)")
    conn.commit()
    conn.close()
    return target


def test_file_uri_is_refused(protected_plain: Path):
    assert refused(f"file:{protected_plain}")


def test_uri_query_suffix_is_refused(protected_plain: Path):
    assert refused(f"{protected_plain}?mode=rw")


def test_trailing_whitespace_is_refused(protected_plain: Path):
    assert refused(f"{protected_plain} ")


def test_hardlink_is_refused_by_identity(protected_plain: Path, tmp_path: Path):
    """The inode is the same file: identity catches what the path cannot."""
    alias = tmp_path / "plainvault" / "innocent.db"
    try:
        os.link(protected_plain, alias)
    except (OSError, NotImplementedError):
        pytest.skip("hardlinks unavailable on this platform")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_schema_version": 1,
                "entries": [
                    {
                        "path": str(protected_plain),
                        "dev": os.stat(protected_plain).st_dev,
                        "ino": os.stat(protected_plain).st_ino,
                        "bytes": protected_plain.stat().st_size,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert refused_with(alias, manifest) is True


def test_byte_identical_copy_is_refused(protected_plain: Path, tmp_path: Path):
    copy = tmp_path / "backup" / "snapshot.db"
    copy.parent.mkdir()
    copy.write_bytes(protected_plain.read_bytes())
    manifest = tmp_path / "manifest2.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_schema_version": 1,
                "entries": [
                    {
                        "path": str(protected_plain),
                        "bytes": copy.stat().st_size,
                        "sha256": hashlib.sha256(copy.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert refused_with(copy, manifest) is True


def test_manifest_listed_path_is_refused(tmp_path: Path):
    protected = tmp_path / "vault2" / "governance.db"
    protected.parent.mkdir()
    protected.write_bytes(b"x")
    manifest = tmp_path / "m3.json"
    manifest.write_text(
        json.dumps({"manifest_schema_version": 1, "entries": [{"path": str(protected)}]}),
        encoding="utf-8",
    )
    assert refused_with(protected, manifest) is True


def test_unreadable_manifest_fails_closed(tmp_path: Path):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProductionDatabaseRefused):
        assert_not_production(str(tmp_path / "candidates.db"), str(bad))


def test_missing_explicit_manifest_fails_closed(tmp_path: Path):
    with pytest.raises(ProductionDatabaseRefused):
        assert_not_production(str(tmp_path / "candidates.db"), str(tmp_path / "absent.json"))


def test_manifest_coverage_reports_hardlink_protection(tmp_path: Path):
    protected = tmp_path / "vault3" / "governance.db"
    protected.parent.mkdir()
    protected.write_bytes(b"x")
    manifest = tmp_path / "m4.json"
    stat = protected.stat()
    manifest.write_text(
        json.dumps(
            {
                "manifest_schema_version": 1,
                "entries": [{"path": str(protected), "dev": stat.st_dev, "ino": stat.st_ino}],
            }
        ),
        encoding="utf-8",
    )
    coverage = manifest_coverage(str(manifest))
    assert coverage["hardlink_protection"] is True
    assert coverage["entries"] == 1


# ------------------------------------------------------- structural guards
def test_only_ledger_opens_a_writable_connection():
    """Static scan: sqlite3.connect in src/ must live in the ledger module."""
    src = Path(__file__).resolve().parents[2] / "src" / "translation_agent"
    offenders = []
    for path in src.rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if (
                "sqlite3.connect" in line
                and path.name != "sqlite_ledger.py"
                and ":memory:" not in line
            ):
                offenders.append(f"{path.relative_to(src.parent.parent)}:{lineno}")
    assert offenders == [], f"writable connection outside the ledger: {offenders}"


def test_export_with_zero_approved_exits_nonzero(tmp_path: Path):
    from translation_agent.export.candidate_export import ExportRefused, export_approved
    from translation_agent.ledger.sqlite_ledger import SqliteLedger

    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        with pytest.raises(ExportRefused):
            export_approved(ledger, str(tmp_path / "out.json"))


def test_cli_export_fails_with_nonzero_exit(tmp_path: Path):
    db = str(tmp_path / "c.db")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    init = subprocess.run(
        [sys.executable, "-m", "translation_agent.cli", "init", "--db", db],
        env=env, capture_output=True, text=True,
    )
    assert init.returncode == 0, init.stderr
    export = subprocess.run(
        [sys.executable, "-m", "translation_agent.cli", "export", "--db", db, "--out",
         str(tmp_path / "approved.json")],
        env=env, capture_output=True, text=True,
    )
    assert export.returncode != 0
    assert "ExportRefused" in export.stderr


# --- TASK 021: manifest identity must not depend on the target existing ---

def write_manifest(tmp_path: Path, entries: list[dict], captured_at: str = "2026-11-09T00:00:00Z") -> Path:
    path = tmp_path / "protected.json"
    path.write_text(
        json.dumps(
            {
                "manifest_schema_version": 1,
                "tool_version": "0.1",
                "captured_at": captured_at,
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_manifest_listed_path_is_refused_before_it_exists(tmp_path: Path):
    """The reservation, not the current file, is what protects the location."""
    reserved = tmp_path / "build" / "production.sqlite"
    manifest = write_manifest(tmp_path, [{"path": str(reserved)}])
    assert not reserved.exists()
    assert refused_with(reserved, manifest) is True


def test_manifest_entry_with_bad_sha256_fails_closed(tmp_path: Path):
    manifest = write_manifest(
        tmp_path, [{"path": str(tmp_path / "x.sqlite"), "sha256": "not-a-hash", "bytes": 1}]
    )
    with pytest.raises(Exception) as excinfo:
        assert_not_production(str(tmp_path / "safe.db"), str(manifest))
    assert "sha256" in str(excinfo.value)


def test_manifest_entry_with_non_integer_inode_fails_closed(tmp_path: Path):
    manifest = write_manifest(
        tmp_path, [{"path": str(tmp_path / "x.sqlite"), "dev": "1", "ino": "2"}]
    )
    with pytest.raises(Exception) as excinfo:
        assert_not_production(str(tmp_path / "safe.db"), str(manifest))
    assert "non-integer" in str(excinfo.value)


def test_manifest_without_entry_path_fails_closed(tmp_path: Path):
    manifest = write_manifest(tmp_path, [{"dev": 1, "ino": 2}])
    with pytest.raises(Exception) as excinfo:
        assert_not_production(str(tmp_path / "safe.db"), str(manifest))
    assert "path" in str(excinfo.value)


def test_guard_reports_manifest_age_and_staleness(tmp_path: Path):
    manifest = write_manifest(tmp_path, [{"path": str(tmp_path / "x.sqlite")}], "2020-01-01T00:00:00Z")
    coverage = manifest_coverage(str(manifest))
    assert coverage["captured_at"] == "2020-01-01T00:00:00Z"
    assert coverage["stale"] is True
    assert coverage["max_age_days"] == 30


def test_fresh_manifest_is_not_stale(tmp_path: Path):
    manifest = write_manifest(tmp_path, [{"path": str(tmp_path / "x.sqlite")}])
    coverage = manifest_coverage(str(manifest))
    assert coverage["stale"] is False
