"""Pytest fixtures.

Keeps the API test-suite deterministic and hermetic: AI generation is turned
off, so missing-word lookups return ``None`` without touching a live LLM
provider. Failover behavior itself is tested separately with fake providers
(see tests/test_failover.py).

Runtime stores are isolated too. The AI cache has its own file now
(data/runtime/ai_cache.sqlite), and a test that wrote a row there used to leave
it behind for the next run, flipping ``first.cached`` to True. Every test now
points the cache at its own temp dir, and a session fixture fails the run if the
real cache or the pinned dictionary changed while the suite ran.
"""

import hashlib
import os
import re
from pathlib import Path

import pytest

from app.core.config import settings

BACKEND = Path(__file__).resolve().parents[1]
_REAL_CACHE = BACKEND / "data" / "runtime" / "ai_cache.sqlite"
_PINNED_DB = BACKEND / "data" / "build" / "dictionary.sqlite"


@pytest.fixture(autouse=True)
def _disable_ai():
    """Disable AI for the whole suite; restore after each test."""
    previous = settings.ai_enabled
    settings.ai_enabled = False
    yield
    settings.ai_enabled = previous


@pytest.fixture(autouse=True)
def _isolate_runtime_cache(tmp_path, monkeypatch):
    """Every test gets its own runtime cache, so no test reads another's rows."""
    monkeypatch.setattr(settings, "ai_cache_path", str(tmp_path / "ai_cache.sqlite"))
    yield


def _sha(p: Path):
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="session", autouse=True)
def _real_stores_untouched():
    """Fail the suite if it modified the real runtime cache or the pinned DB."""
    before = (_sha(_REAL_CACHE), _sha(_PINNED_DB))
    yield
    after = (_sha(_REAL_CACHE), _sha(_PINNED_DB))
    if before[0] != after[0]:
        pytest.fail("the suite modified the real runtime AI cache")
    if before[1] != after[1]:
        pytest.fail("the suite modified the pinned dictionary.sqlite")
