"""Pytest fixtures.

Keeps the API test-suite deterministic and hermetic: AI generation is turned
off, so missing-word lookups return ``None`` without touching a live LLM
provider. Failover behavior itself is tested separately with fake providers
(see tests/test_failover.py).
"""

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _disable_ai():
    """Disable AI for the whole suite; restore after each test."""
    previous = settings.ai_enabled
    settings.ai_enabled = False
    yield
    settings.ai_enabled = previous
