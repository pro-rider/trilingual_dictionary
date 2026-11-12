"""Guards for PROTOCOL.md rules 2, 3, 8 and 9.

Each test has a negative control next to it: the detector is required to fire on
bad input, not merely to stay quiet on good input. A check that only proves
"nothing was reported" is the vacuous success this protocol exists to stop.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

import check_encoding  # noqa: E402
import preflight  # noqa: E402

FIXTURE = os.path.join(BACKEND, "data", "test_fixtures", "dictionary_fixture.sqlite")


# --------------------------------------------------------------------- encoding

def _make_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE senses (sense_id INTEGER PRIMARY KEY, gloss_ne TEXT, gloss_en TEXT)")
    for index, gloss in enumerate(rows, 1):
        conn.execute("INSERT INTO senses VALUES (?, ?, 'book')", (index, gloss))
    conn.commit()
    conn.close()


def test_clean_text_reports_no_errors(tmp_path):
    db = tmp_path / "clean.sqlite"
    _make_db(db, ["किताब", "कापी", "कुर्सी"])
    report = check_encoding.check_database(db, strict=True)
    assert report["errors"] == []
    assert report["ok"] is True


def test_replacement_character_is_caught(tmp_path):
    db = tmp_path / "bad.sqlite"
    _make_db(db, ["किताब", "कापी\ufffd"])
    report = check_encoding.check_database(db)
    assert report["ok"] is False
    assert any("U+FFFD" in e["reason"] for e in report["errors"])


def test_mojibake_without_replacement_character_is_caught(tmp_path):
    db = tmp_path / "moji.sqlite"
    # Double-decoded Devanagari: valid UTF-8, no U+FFFD, still wrong.
    _make_db(db, ["à¤•à¤¿à¤¤à¤¾à¤¬"])
    report = check_encoding.check_database(db)
    assert report["ok"] is False
    assert any("mojibake" in e["reason"] for e in report["errors"])


def test_latin_in_nepali_column_warns_and_strict_mode_fails(tmp_path):
    db = tmp_path / "latin.sqlite"
    _make_db(db, ["book"])
    loose = check_encoding.check_database(db)
    strict = check_encoding.check_database(db, strict=True)
    assert loose["ok"] is True, "a warning alone must not fail a normal run"
    assert strict["ok"] is False, "strict mode must escalate the warning"


def test_encoding_selftest_detector_bites():
    report = check_encoding.selftest()
    assert report["ok"] is True, report
    assert report["caught_errors"] is True
    assert report["caught_devanagari_warning"] is True


def test_encoding_cli_exits_nonzero_on_failure(tmp_path):
    db = tmp_path / "bad.sqlite"
    _make_db(db, ["\ufffd"])
    assert check_encoding.main(["--db", str(db)]) == 1
    clean = tmp_path / "clean.sqlite"
    _make_db(clean, ["किताब"])
    assert check_encoding.main(["--db", str(clean)]) == 0


def test_committed_fixture_is_encoding_clean():
    """The database CI actually tests against must not contain mojibake."""
    if not os.path.exists(FIXTURE):
        import pytest
        pytest.skip("committed fixture missing: %s" % FIXTURE)
    report = check_encoding.check_database(__import__("pathlib").Path(FIXTURE))
    assert report["ok"] is True, json.dumps(report["errors"][:5], ensure_ascii=False)


# --------------------------------------------------------------------- preflight

GIT_FALLBACKS = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
)


def _git_exe():
    """Resolve git even when it is installed but not on PATH.

    A Windows box can have Git installed and still hand the test runner a PATH
    without it; failing five tests over that is a portability defect in the
    test, not a defect in preflight.
    """
    found = shutil.which("git")
    if found:
        return found
    for candidate in GIT_FALLBACKS:
        if os.path.exists(candidate):
            return candidate
    return "git"


def _git(repo, *args):
    result = subprocess.run([_git_exe(), *args], cwd=str(repo), capture_output=True,
                            text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    return result.stdout


def _repo_with_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "baseline")
    return repo


def test_preflight_proceeds_on_clean_tree(tmp_path):
    repo = _repo_with_commit(tmp_path)
    report = preflight.evaluate(repo=repo, intent="no-op", skip_pins=True)
    assert report["ok"] is True, report
    assert report["verdict"] == "PROCEED"


def test_preflight_stops_on_dirty_tree(tmp_path):
    repo = _repo_with_commit(tmp_path)
    (repo / "README.md").write_text("edited\n", encoding="utf-8")
    report = preflight.evaluate(repo=repo, intent="bulk rewrite", skip_pins=True)
    assert report["ok"] is False
    assert report["verdict"] == "STOP"
    git_check = [c for c in report["checks"] if c["name"] == "git_clean"][0]
    assert "README.md" in git_check["paths"]


def test_preflight_allow_dirty_is_explicit_not_default(tmp_path):
    repo = _repo_with_commit(tmp_path)
    (repo / "README.md").write_text("edited\n", encoding="utf-8")
    report = preflight.evaluate(repo=repo, intent="read-only audit",
                               skip_pins=True, allow_dirty=True)
    assert report["ok"] is True
    assert report["checks"][0]["overridden"] is True


def test_preflight_requires_a_real_backup(tmp_path):
    repo = _repo_with_commit(tmp_path)
    missing = tmp_path / "absent.sqlite"
    report = preflight.evaluate(repo=repo, intent="migrate", skip_pins=True, backup=missing)
    assert report["ok"] is False

    present = tmp_path / "backup.sqlite"
    present.write_bytes(b"x" * 16)
    report = preflight.evaluate(repo=repo, intent="migrate", skip_pins=True, backup=present)
    assert report["ok"] is True
    assert report["checks"][2]["sha256"] == preflight.sha256_file(present)


def test_preflight_cli_exit_codes(tmp_path):
    repo = _repo_with_commit(tmp_path)
    assert preflight.main(["--intent", "no-op", "--skip-pins", "--repo", str(repo)]) == 0
    (repo / "README.md").write_text("edited\n", encoding="utf-8")
    assert preflight.main(["--intent", "bulk", "--skip-pins", "--repo", str(repo)]) == 1
