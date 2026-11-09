"""Make a consistent copy of a SQLite database using the online backup API.

A plain file copy of a live database can capture a torn page set; this tool
uses ``Connection.backup`` and then verifies the copy with ``integrity_check``.
It refuses to write onto the source or onto a protected path.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

from translation_agent.config import ProductionDatabaseRefused, assert_not_production

try:  # imported as a package (tests) vs executed as a script (CLI)
    from .capture_pins import capture_pins
except ImportError:  # pragma: no cover
    from capture_pins import capture_pins


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(a) == os.path.realpath(b)


def safe_copy(source: str, destination: str) -> dict:
    src = str(Path(source).resolve())
    if not Path(src).exists():
        raise FileNotFoundError(src)
    dst = str(Path(destination).absolute())
    if _same_file(src, dst):
        raise ValueError("destination is the source; refusing to overwrite")
    # Destination may not be a protected/production path.
    dst = assert_not_production(dst)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)

    source_pin_before = capture_pins(src)
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(dst)
        try:
            src_conn.backup(dst_conn)
            integrity = dst_conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dst_conn.close()
    finally:
        src_conn.close()

    source_pin_after = capture_pins(src)
    if source_pin_before["sha256"] != source_pin_after["sha256"]:
        raise RuntimeError("source changed during copy")

    copy_pin = capture_pins(dst)
    if integrity != "ok":
        raise RuntimeError(f"copy failed integrity_check: {integrity}")
    if copy_pin["tables"] != source_pin_before["tables"]:
        raise RuntimeError(
            f"copy row counts differ: {copy_pin['tables']} vs {source_pin_before['tables']}"
        )
    return {
        "source": src,
        "destination": dst,
        "source_pin_before": source_pin_before,
        "source_pin_after": source_pin_after,
        "copy_pin": copy_pin,
        "integrity_check": integrity,
        "copy_sha256": _sha256(dst),
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: safe_copy.py <source> <destination>", file=sys.stderr)
        return 2
    try:
        report = safe_copy(argv[0], argv[1])
    except (ProductionDatabaseRefused, ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
