"""Capture a database "pin": identity that can be compared before/after a run.

Read-only by construction: the connection uses a ``mode=ro`` URI and the tool
never issues a write.  Destination-free: this tool writes only the JSON it
prints, never the database.

Pin format (proposal; must be reconciled with docs/ASSET-PINS.json before use):

    {
      "pin_schema_version": 1, "tool_version": "0.1",
      "path": "...", "sha256": "...", "bytes": N,
      "user_version": N,
      "schema_sha256": "...",          # sha256 over ordered sqlite_master DDL
      "tables": {"name": rows, ...},
      "captured_at": "..."
    }
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PIN_SCHEMA_VERSION = 1
TOOL_VERSION = "0.1"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ro_uri(path: str) -> str:
    # No 'immutable=1': it lies about databases in WAL mode.
    return f"file:{Path(path).resolve()}?mode=ro"


def open_read_only(path: str) -> sqlite3.Connection:
    return sqlite3.connect(_ro_uri(path), uri=True)


def schema_digest(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    payload = "\n".join("|".join(str(part) for part in row) for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def capture_pins(path: str) -> dict:
    resolved = str(Path(path).resolve())
    if not Path(resolved).exists():
        raise FileNotFoundError(resolved)
    before = _sha256_file(resolved)
    conn = open_read_only(resolved)
    try:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        schema = schema_digest(conn)
        tables = {
            name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    after = _sha256_file(resolved)
    if before != after:
        raise RuntimeError("database changed while being pinned; refusing to report a pin")
    return {
        "pin_schema_version": PIN_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "path": resolved,
        "sha256": before,
        "bytes": Path(resolved).stat().st_size,
        "user_version": user_version,
        "schema_sha256": schema,
        "tables": dict(sorted(tables.items())),
        "integrity_check": integrity,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: capture_pins.py <database> [<database> ...]", file=sys.stderr)
        return 2
    pins = []
    for path in argv:
        try:
            pins.append(capture_pins(path))
        except Exception as exc:  # noqa: BLE001 - CLI boundary
            print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    print(json.dumps({"pins": pins}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
