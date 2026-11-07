import json
from pathlib import Path
from typing import Any

from app.core.config import settings


def load_entries() -> list[dict[str, Any]]:
    """Load the canonical dataset once (v1 reads from JSON; Postgres later)."""
    path = Path(settings.dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("entries", [])


def find_entry(query: str, lang: str) -> dict[str, Any] | None:
    """Exact → prefix lookup on the canonical dataset."""
    q = query.strip().lower()
    entries = load_entries()

    for e in entries:
        if lang == "zh":
            if any(
                s.get("word_zh", "").strip() == q for s in e.get("senses", [])
            ):
                return e
        else:
            if e.get("word_en", "").strip().lower() == q:
                return e

    # Prefix fallback
    for e in entries:
        if lang == "zh":
            if any(
                s.get("word_zh", "").startswith(q)
                for s in e.get("senses", [])
            ):
                return e
        else:
            if e.get("word_en", "").strip().lower().startswith(q):
                return e
    return None
