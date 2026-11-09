"""Print a canonical content fingerprint for a SQLite file.

The definition lives in ``app.translations.schema.content_fingerprint`` and is
reproduced here so two people comparing evidence use the same rules:

    scope      every user table; sqlite_* internals excluded
    per row    every column in declared order, str() form, None -> \\x00NULL
    order      primary key, else every column
    separators \\x1e between fields, \\x1d between rows
    normalise  none — bytes as stored (no NFC/NFKC, no whitespace or case folding)
    per table  sha256 of the stream + row count
    combined   sha256 over "v<user_version>" and "table|rows|sha" sorted by table
    excluded   page layout, WAL state, rowid when undeclared, file bytes

Usage:
  python tools/fingerprint.py --db backend/data/build/translations.db
"""
from __future__ import annotations

import argparse
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.translations import schema  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="SQLite file to fingerprint")
    args = ap.parse_args(argv)
    result = schema.content_fingerprint(args.db)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result and result["integrity"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
