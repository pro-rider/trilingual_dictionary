"""Verify free eligibility from the provider's own catalogue, not from articles.

Rules encoded here:

* A model counts as free only when the catalogue reports **both** prices as
  zero. Missing pricing is ``UNKNOWN`` and is treated as *not free*.
* The ``:free`` suffix alone is not evidence — it is a naming convention that
  can be renamed. Pricing is the evidence.
* Anything that cannot be fetched keeps the previous snapshot but marks the
  verification stale, so callers can decide to fail closed.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
UA = "trilingual-dictionary/1.0 (free-model verification)"


@dataclass
class CatalogResult:
    ok: bool
    models: dict[str, dict]      # id -> raw model record (only zero-priced ones)
    source: str
    fetched_at: str
    error: str = ""

    @property
    def count(self) -> int:
        return len(self.models)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def zero_priced(records: list[dict]) -> dict[str, dict]:
    """Keep records whose prompt *and* completion prices are exactly 0."""
    out: dict[str, dict] = {}
    for rec in records:
        pricing = rec.get("pricing") or {}
        if str(pricing.get("prompt")) == "0" and str(pricing.get("completion")) == "0":
            out[rec.get("id", "")] = rec
    out.pop("", None)
    return out


def fetch_catalog(timeout: float = 20) -> CatalogResult:
    req = urllib.request.Request(OPENROUTER_MODELS_URL, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except Exception as exc:                        # noqa: BLE001 - reported, not raised
        return CatalogResult(False, {}, "openrouter /api/v1/models", _now_iso(),
                             error=type(exc).__name__)
    records = payload.get("data") or []
    return CatalogResult(True, zero_priced(records), "openrouter /api/v1/models", _now_iso())


def cache_path() -> Path:
    raw = os.environ.get("AI_MODEL_CACHE_FILE", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "data" / "ai" / "free_models.json"


def load_cache(path: Path | None = None) -> CatalogResult | None:
    p = path or cache_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return CatalogResult(True, data.get("models") or {},
                         data.get("source", ""), data.get("fetched_at", ""))


def save_cache(result: CatalogResult, path: Path | None = None) -> Path:
    p = path or cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"models": result.models, "source": result.source,
                             "fetched_at": result.fetched_at}, indent=1),
                 encoding="utf-8")
    return p


def _age_hours(fetched_at: str) -> float | None:
    try:
        stamp = time.strptime(fetched_at, "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None
    return (time.time() - time.mktime(stamp) + time.timezone) / 3600.0


def refresh(*, enabled: bool = True, path: Path | None = None,
            interval_hours: float = 24.0) -> CatalogResult:
    """Fetch live when the cached verification is stale; else reuse the cache.

    Never queries the catalogue on every request — that would turn a free-tier
    guard into a rate-limit generator.
    """
    cached = load_cache(path)
    fresh = cached is not None and (_age_hours(cached.fetched_at) or 1e9) < interval_hours
    if fresh:
        return cached
    if enabled:
        live = fetch_catalog()
        if live.ok:
            save_cache(live, path)
            return live
    if cached is not None:
        return cached
    return CatalogResult(False, {}, "no cache", "", error="catalogue unavailable")
