"""Disposable-email domains: a speed bump, not a wall.

Two sources, merged at import:

1. ``backend/data/disposable_email_seed.txt`` — shipped with the repo, hand
   written from publicly documented throwaway providers. It is deliberately
   small: it is a floor, not the whole list.
2. An optional generated list at ``backend/data/disposable_email_blocklist.conf``
   (path overridable with ``DISPOSABLE_LIST_PATH``). The update script
   (``backend/tools/update_disposable_domains.py``) fetches it from
   disposable-email-domains/disposable-email-domains.

Why the big list is not vendored: as of 2026-11 the upstream repository reports
licence ``NOASSERTION`` ("Other"), so redistribution inside this repo is not
something we can assume. It is therefore a deploy-time artifact, generated on
the server, and git-ignored.

A blocked domain is a *domain-level* decision, so refusing it never reveals
whether a specific address exists. ``auth_disposable_allow_domains`` is the
manual override for the inevitable false positive (a company using a vanity
mail domain that happens to be listed): a real user who writes in gets unblocked
by adding their domain to that comma-separated env value, no redeploy needed.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.core.config import settings

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SEED_PATH = _DATA_DIR / "disposable_email_seed.txt"


def _read_domains(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    out = set()
    for line in text.splitlines():
        line = line.strip().lower()
        if not line or line.startswith("#"):
            continue
        out.add(line.lstrip("*."))
    return out


def _generated_path() -> Path:
    raw = os.environ.get("DISPOSABLE_LIST_PATH", "").strip()
    return Path(raw) if raw else _DATA_DIR / "disposable_email_blocklist.conf"


def _allow_list() -> set[str]:
    raw = (os.environ.get("AUTH_DISPOSABLE_ALLOW_DOMAINS")
           or settings.auth_disposable_allow_domains or "")
    return {part.strip().lower().lstrip("*.") for part in raw.split(",") if part.strip()}


_BLOCKED: set[str] | None = None
_SEED_COUNT = 0
_GENERATED_COUNT = 0


def _load() -> set[str]:
    global _BLOCKED, _SEED_COUNT, _GENERATED_COUNT
    if _BLOCKED is None:
        seed = _read_domains(SEED_PATH)
        generated = _read_domains(_generated_path())
        _SEED_COUNT = len(seed)
        _GENERATED_COUNT = len(generated)
        _BLOCKED = seed | generated
    return _BLOCKED


def reload() -> None:
    """Forget the cache (tests, and after the update script runs)."""
    global _BLOCKED
    _BLOCKED = None


def stats() -> dict[str, int]:
    _load()
    return {"seed": _SEED_COUNT, "generated": _GENERATED_COUNT, "total": len(_BLOCKED or set())}


def domain_of(email: str) -> str:
    return email.strip().lower().rpartition("@")[2]


def is_disposable(email: str) -> bool:
    domain = domain_of(email)
    if not domain:
        return False
    if domain in _allow_list():
        return False
    blocked = _load()
    if domain in blocked:
        return True
    # A subdomain of a throwaway provider is throwaway too (x.mailinator.com).
    parent = domain
    while "." in parent:
        parent = parent.split(".", 1)[1]
        if parent in blocked and "." in parent:
            return True
    return False
