"""Static guards: the pinned dictionary must never be opened for writing.

The pin guard (tools/check_asset_pin.py) detects drift after the fact. These
tests catch the cause: any module under app/ that names the pinned DB must open
it read-only, and the runtime cache must not touch it at all.

Regression being prevented: ai_cache.py opened dictionary.sqlite read-write, so
one AI lookup changed the fingerprint of a shipped asset and the pin guard was
red for weeks.
"""

import os
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _py_files(root: Path):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


def test_only_read_only_connections_to_the_pinned_dictionary():
    """Any module that OPENS the pinned DB must do it with mode=ro.

    Declaring the path in config is fine; connecting without mode=ro is not.
    """
    offenders = []
    for f in _py_files(BACKEND / "app"):
        text = f.read_text(encoding="utf-8")
        if "sqlite3.connect" not in text:
            continue
        if "dictionary_db_path" not in text:
            continue
        if "mode=ro" not in text:
            offenders.append(str(f.relative_to(BACKEND)))
    assert not offenders, (
        "pinned dictionary opened without mode=ro: " + ", ".join(offenders)
    )


def test_runtime_cache_does_not_touch_the_pinned_dictionary():
    text = (BACKEND / "app" / "services" / "ai_cache.py").read_text(encoding="utf-8")
    assert "dictionary_db_path" not in text, (
        "ai_cache must not open the pinned dictionary; it has its own store"
    )
    assert "ai_cache_path" in text


def test_cache_never_attaches_or_joins_the_dictionary():
    text = (BACKEND / "app" / "services" / "ai_cache.py").read_text(encoding="utf-8").upper()
    assert "ATTACH" not in text
    assert not re.search(r"JOIN\s+ENTRIES|JOIN\s+SENSES", text)


def test_cache_path_is_anchored_so_the_cwd_does_not_matter(tmp_path, monkeypatch):
    """A relative cache path must resolve under backend/, not the launch folder."""
    from app.core.config import settings
    from app.services import ai_cache

    monkeypatch.setattr(settings, "ai_cache_path", "data/runtime/ai_cache.sqlite")
    p = ai_cache._path()
    assert p.is_absolute()
    assert p.parents[1].name == "data" or (p.parents[2] / "app").exists()
    assert "backend" in str(p)
