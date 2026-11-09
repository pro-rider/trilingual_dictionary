"""Configuration and the production-database guard.

The guard used to be name-and-fragment only, which three tests showed to be
bypassable (``?mode=rw``, trailing whitespace, hard links).  It now combines
independent controls:

1. ambiguous input is refused outright (SQLite URIs, query suffixes, control
   characters, leading/trailing whitespace);
2. filename and path-fragment rules (kept — they are cheap and catch the
   common mistake);
3. **file identity**: a protected-file manifest records ``(dev, ino)`` and
   ``sha256`` for each production database.  A hard link, which no path rule
   can see, is caught by the inode comparison; a copy is caught by the size +
   content hash comparison;
4. fail-closed: if the target exists but cannot be stat'ed, or if a configured
   manifest cannot be parsed, the guard refuses instead of guessing.

The manifest is produced by ``scripts/protect_manifest.py`` on the machine that
holds the real database.  Without a manifest, hard-link protection is
unavailable and the guard says so (``manifest_coverage()``).
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
from datetime import datetime, timezone
import re
from dataclasses import dataclass, field


PRODUCTION_DB_NAMES = {"dictionary.sqlite", "translations.db"}
PRODUCTION_PATH_MARKERS = ("backend/data/build", "assets/data")

_ALLOWED_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_MANIFEST_MAX_AGE_DAYS = 30
_MANIFEST_ENV = "TRANSLATION_AGENT_PROTECTED_MANIFEST"
_MANIFEST_SCHEMA_VERSION = 1


class ProductionDatabaseRefused(RuntimeError):
    """Raised when a path resolves to a shipped/production database."""


class AmbiguousPathRefused(ProductionDatabaseRefused):
    """Raised for SQLite URI syntax, query suffixes, or whitespace ambiguity."""


class UnverifiableProtectedIdentity(ProductionDatabaseRefused):
    """Raised when protection cannot be established (fail closed)."""


def _hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def refuse_ambiguous(path: str) -> str:
    """Reject input that is not a plain filesystem path."""
    if not isinstance(path, str):
        raise AmbiguousPathRefused(f"ledger path must be str, got {type(path).__name__}")
    if not path.strip():
        raise AmbiguousPathRefused("ledger path is empty")
    if path != path.strip():
        raise AmbiguousPathRefused(
            f"refusing path with leading/trailing whitespace: {path!r}"
        )
    if _CONTROL_CHARS.search(path):
        raise AmbiguousPathRefused(f"refusing path with control characters: {path!r}")
    lowered = path.lower()
    if lowered.startswith("file:") or "://" in path:
        raise AmbiguousPathRefused(f"refusing SQLite URI form: {path!r}")
    if "?" in path or "#" in path:
        raise AmbiguousPathRefused(
            f"refusing path with URI query/fragment syntax: {path!r}"
        )
    return path


def load_manifest(path: str | None = None) -> dict:
    """Read the protected-file manifest.  Missing manifest is allowed and reported."""
    explicit = path or os.environ.get(_MANIFEST_ENV)
    candidate = pathlib.Path(explicit).expanduser() if explicit else pathlib.Path("protected-databases.json")
    if not candidate.exists():
        if explicit:
            raise UnverifiableProtectedIdentity(
                f"protected manifest {candidate} does not exist; refusing to guess"
            )
        return {"manifest_schema_version": _MANIFEST_SCHEMA_VERSION, "source": None, "entries": []}
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UnverifiableProtectedIdentity(
            f"protected manifest {candidate} is unreadable: {exc}"
        ) from exc
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise UnverifiableProtectedIdentity(
            f"protected manifest {candidate} has no 'entries' list"
        )
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"]:
            raise UnverifiableProtectedIdentity(
                f"protected manifest {candidate} has a malformed entry (path): {entry!r}"
            )
        for key in ("dev", "ino", "bytes"):
            if key in entry and entry[key] is not None and not isinstance(entry[key], int):
                raise UnverifiableProtectedIdentity(
                    f"protected manifest {candidate} entry {entry['path']!r} has non-integer {key}"
                )
        if entry.get("sha256") is not None:
            digest = entry["sha256"]
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
                raise UnverifiableProtectedIdentity(
                    f"protected manifest {candidate} entry {entry['path']!r} has a malformed sha256"
                )
    captured = data.get("captured_at")
    if captured is not None and not isinstance(captured, str):
        raise UnverifiableProtectedIdentity(
            f"protected manifest {candidate} has a non-string captured_at"
        )
    data.setdefault("manifest_schema_version", _MANIFEST_SCHEMA_VERSION)
    data["source"] = str(candidate.resolve())
    return data


def _manifest_age_days(captured_at: str | None) -> float | None:
    if not captured_at:
        return None
    try:
        stamp = datetime.strptime(captured_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400.0


def manifest_coverage(manifest_path: str | None = None) -> dict:
    """What protection is actually active — used in reports, never assumed."""
    manifest = load_manifest(manifest_path)
    entries = manifest["entries"]
    age = _manifest_age_days(manifest.get("captured_at"))
    return {
        "source": manifest.get("source"),
        "entries": len(entries),
        "inode_identity": any(e.get("dev") is not None and e.get("ino") is not None for e in entries),
        "content_identity": any(e.get("sha256") for e in entries),
        "hardlink_protection": any(e.get("dev") is not None and e.get("ino") is not None for e in entries),
        "captured_at": manifest.get("captured_at"),
        "age_days": round(age, 1) if age is not None else None,
        "stale": bool(age is not None and age > _MANIFEST_MAX_AGE_DAYS),
        "max_age_days": _MANIFEST_MAX_AGE_DAYS,
    }


def assert_not_production(path: str, manifest_path: str | None = None) -> str:
    """Return the resolved path, or raise if it is, aliases, or copies a production store."""
    raw = refuse_ambiguous(str(path))
    resolved = pathlib.Path(os.path.realpath(str(pathlib.Path(raw).expanduser())))
    name = resolved.name.lower()
    if name in PRODUCTION_DB_NAMES:
        raise ProductionDatabaseRefused(
            f"refusing to open production database by name: {resolved}"
        )
    normalised = str(resolved).replace("\\", "/").lower()
    for marker in PRODUCTION_PATH_MARKERS:
        if marker in normalised:
            raise ProductionDatabaseRefused(
                f"refusing to open a database under protected path {marker!r}: {resolved}"
            )

    entries = load_manifest(manifest_path)["entries"]

    # Path identity is checked before existence: a manifest-listed path must be
    # refused even when the file is absent, otherwise SQLite would happily
    # create a new database at the reserved location.
    for entry in entries:
        entry_path = os.path.realpath(str(entry["path"]))
        if os.path.normcase(str(resolved)) == os.path.normcase(entry_path):
            raise ProductionDatabaseRefused(
                f"refusing protected file listed in the manifest: {resolved}"
            )

    if resolved.exists():
        try:
            stat = os.stat(resolved)
        except OSError as exc:
            raise UnverifiableProtectedIdentity(
                f"cannot stat {resolved}: {exc}"
            ) from exc
        if not os.path.isfile(resolved):
            raise ProductionDatabaseRefused(f"refusing non-regular file: {resolved}")

        for entry in entries:
            entry_path = os.path.realpath(str(entry["path"]))
            if entry.get("dev") is not None and entry.get("ino") is not None:
                if (stat.st_dev, stat.st_ino) == (entry["dev"], entry["ino"]):
                    raise ProductionDatabaseRefused(
                        f"refusing {resolved}: it is the same file (dev/ino) as protected {entry_path}"
                    )
            if entry.get("sha256") and entry.get("bytes") == stat.st_size:
                if _hash_file(str(resolved)) == entry["sha256"]:
                    raise ProductionDatabaseRefused(
                        f"refusing {resolved}: byte-identical copy of protected {entry_path}"
                    )
    return str(resolved)


def assert_ledger_suffix(path: str) -> str:
    suffix = pathlib.Path(path).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise ValueError(f"ledger must use one of {sorted(_ALLOWED_SUFFIXES)}, got {path!r}")
    return path


@dataclass(frozen=True)
class AgentConfig:
    ledger_path: str
    target_language: str = "ne"
    max_attempts: int = 2
    raw_response_max_bytes: int = 16384
    retention_days: int = 30
    provider: str = "fake"
    model: str = "fake-v1"
    protected_manifest: str | None = None
    busy_retries: int = 5
    busy_backoff_ms: int = 20

    @classmethod
    def from_env(cls, ledger_path: str | None = None) -> "AgentConfig":
        return cls(
            ledger_path=ledger_path
            or os.environ.get("TRANSLATION_AGENT_LEDGER", "./data/candidates.db"),
            target_language=os.environ.get("TRANSLATION_AGENT_TARGET_LANGUAGE", "ne"),
            max_attempts=int(os.environ.get("TRANSLATION_AGENT_MAX_ATTEMPTS", "2")),
            raw_response_max_bytes=int(
                os.environ.get("TRANSLATION_AGENT_RAW_MAX_BYTES", "16384")
            ),
            retention_days=int(os.environ.get("TRANSLATION_AGENT_RETENTION_DAYS", "30")),
            provider=os.environ.get("TRANSLATION_AGENT_PROVIDER", "fake"),
            model=os.environ.get("TRANSLATION_AGENT_MODEL", "fake-v1"),
            protected_manifest=os.environ.get(_MANIFEST_ENV),
            busy_retries=int(os.environ.get("TRANSLATION_AGENT_BUSY_RETRIES", "5")),
            busy_backoff_ms=int(os.environ.get("TRANSLATION_AGENT_BUSY_BACKOFF_MS", "20")),
        )

    def validate(self) -> "AgentConfig":
        assert_ledger_suffix(self.ledger_path)
        assert_not_production(self.ledger_path, self.protected_manifest)
        if self.max_attempts < 1 or self.max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if self.raw_response_max_bytes < 1024:
            raise ValueError("raw_response_max_bytes too small to be useful")
        if self.busy_retries < 0 or self.busy_retries > 20:
            raise ValueError("busy_retries must be between 0 and 20")
        if self.retention_days < 1:
            raise ValueError("retention_days must be >= 1")
        return self
