"""Mechanical guards for the execution contract.

Two things the contract states but nothing enforced until now:

* mandatory checks must return a non-zero exit, never a bare ``assert`` — a
  ``python -O`` run silently removes asserts, which is exactly how a "gate"
  becomes a comment;
* a shipped asset may only change through an approved pin update.
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

GATE_FILES = [
    "build_dictionary.py",
    "r5_import.py",
    "validate_fts.py",
    "rebuild_fts.py",
    "fts_repro_check.py",
    "import_legacy_ne.py",
    "rollback_rehearsal.py",
    "check_translation_golden.py",
    "check_asset_pin.py",
    "classify_script_mix.py",
    "fingerprint.py",
]


@pytest.mark.parametrize("name", GATE_FILES)
def test_gate_scripts_never_use_bare_assert(name):
    path = os.path.join(BACKEND, "tools", name)
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith("assert ") or stripped == "assert":
                pytest.fail("%s:%d uses assert as a check: %s" % (name, lineno, stripped))


def test_every_gate_script_can_report_failure():
    """A gate that cannot return non-zero is not a gate."""
    for name in ("validate_fts.py", "check_asset_pin.py", "check_translation_golden.py"):
        path = os.path.join(BACKEND, "tools", name)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert "SystemExit(main())" in text, name


def test_pins_match_the_files_on_disk():
    import check_asset_pin

    report = check_asset_pin.check()
    assert report["ok"], report["failures"]
    states = {p["path"]: p["state"] for p in report["pins"]}
    assert states["backend/data/build/dictionary.sqlite"] in ("unchanged", "absent")


def test_asset_pin_check_fails_on_a_changed_asset(tmp_path):
    """Prove the guard bites: a modified copy under a fake root must fail."""
    import check_asset_pin

    fake = tmp_path / "repo"
    (fake / "backend" / "data" / "build").mkdir(parents=True)
    target = fake / "backend" / "data" / "build" / "dictionary.sqlite"
    target.write_bytes(b"not the pinned asset")
    pins = tmp_path / "pins.json"
    pins.write_text(
        '{"pins":[{"path":"backend/data/build/dictionary.sqlite","sha256":"%s"}]}'
        % ("0" * 64), encoding="utf-8")
    report = check_asset_pin.check(str(pins), str(fake))
    assert report["ok"] is False
    assert report["pins"][0]["state"] == "CHANGED"
