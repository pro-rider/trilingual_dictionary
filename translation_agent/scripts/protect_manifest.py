"""Capture file identity for protected databases.

Run this on the machine that holds the real database.  The JSON it writes is
what lets the guard recognise a hard link or a byte-identical copy, which no
filename rule can see.

Identity only — the tool never reads the database as a database and never
writes to it.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOL_VERSION = "0.1"
DEFAULT_OUT = "protected-databases.json"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identity_entry(path: str, with_hash: bool = True) -> dict:
    resolved = str(Path(path).resolve())
    stat = Path(resolved).stat()
    entry = {
        "path": resolved,
        "dev": stat.st_dev,
        "ino": stat.st_ino,
        "bytes": stat.st_size,
    }
    if with_hash:
        entry["sha256"] = _sha256(resolved)
    return entry


def capture(paths: list[str], with_hash: bool = True) -> dict:
    entries = [identity_entry(p, with_hash) for p in paths]
    return {
        "manifest_schema_version": 1,
        "tool_version": TOOL_VERSION,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": entries,
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(f"usage: protect_manifest.py [--out {DEFAULT_OUT}] <database> [...]", file=sys.stderr)
        return 2
    out = DEFAULT_OUT
    if argv[0] == "--out":
        if len(argv) < 2:
            print("--out needs a value", file=sys.stderr)
            return 2
        out, argv = argv[1], argv[2:]
    try:
        manifest = capture(argv)
    except OSError as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    Path(out).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": out, "entries": len(manifest["entries"])}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
