"""Independent re-verification of the shipped asset chain (Release Authority).

Checks, without trusting docs/RELEASE.json:
  1. the working DB on disk hashes to the value pinned in docs/ASSET-PINS.json
  2. the packed gz decompresses to exactly the release DB bytes
  3. integrity_check / foreign_key_check pass on the release DB
  4. no forbidden table or unlicensed source survives in the release DB
  5. counts in RELEASE.json match what the release DB actually contains
  6. the client constant matches asset_version
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "backend" / "data" / "build" / "dictionary.sqlite"
RELEASE = REPO / "backend" / "data" / "build" / "release" / "dictionary.release.sqlite"
PACKED = REPO / "assets" / "data" / "dictionary.sqlite.gz"
DART = REPO / "lib" / "data" / "local" / "offline_dictionary.dart"
PINS = REPO / "docs" / "ASSET-PINS.json"
RECORD = REPO / "docs" / "RELEASE.json"

FORBIDDEN_TABLES = [
    "gloss_zh_candidates", "gloss_zh_wikt_candidates", "words3000_candidates",
    "example_candidates", "launch_set", "review_audit", "review_rejected",
    "staging_entries", "staging_senses", "corpus_hits", "import_batches",
    "dictionary_changelog",
]


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    ok = True
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    pins = json.loads(PINS.read_text(encoding="utf-8"))

    # 1. working DB vs pin
    pin = next(p for p in pins["pins"] if p["path"] == "backend/data/build/dictionary.sqlite")
    db_sha, db_size = sha_file(DB), DB.stat().st_size
    match = db_sha == pin["sha256"] and db_size == pin["bytes"]
    print(f"[1] working DB  {db_sha[:16]}  {db_size:,} B   pin {'MATCH' if match else 'MISMATCH'}")
    ok &= match

    # 2. gz -> release DB byte equality
    packed_bytes = PACKED.read_bytes()
    unpacked = gzip.decompress(packed_bytes)
    rel_sha, rel_size = sha_file(RELEASE), RELEASE.stat().st_size
    same_bytes = sha_bytes(unpacked) == rel_sha and len(unpacked) == rel_size
    print(f"[2] release DB  {rel_sha[:16]}  {rel_size:,} B   "
          f"gz unpack {'IDENTICAL' if same_bytes else 'DIFFERS'} ({len(unpacked):,} B)")
    print(f"    packed      {sha_file(PACKED)[:16]}  {len(packed_bytes):,} B")
    ok &= same_bytes
    ok &= record["db_sha256"] == rel_sha
    ok &= record["packed_sha256"] == sha_file(PACKED)
    ok &= record["db_bytes"] == rel_size
    ok &= record["packed_bytes"] == len(packed_bytes)

    # 3-5. inspect the release DB
    work = Path(tempfile.mkdtemp()) / "release.sqlite"
    work.write_bytes(b"")
    with gzip.open(PACKED, "rb") as src, open(work, "wb") as dst:
        dst.write(src.read())
    con = sqlite3.connect(work)
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    present = [t for (t,) in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    leaked = sorted(set(FORBIDDEN_TABLES) & set(present))
    counts = {
        "entries": con.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        "senses": con.execute("SELECT COUNT(*) FROM senses").fetchone()[0],
        "examples": con.execute("SELECT COUNT(*) FROM examples").fetchone()[0],
        "images": con.execute("SELECT COUNT(*) FROM images").fetchone()[0],
        "fts": con.execute("SELECT COUNT(*) FROM fts").fetchone()[0],
        "fts_zh": con.execute("SELECT COUNT(*) FROM fts_zh").fetchone()[0],
    }
    schema = con.execute(
        "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    bad_sources = con.execute(
        "SELECT COUNT(*) FROM senses WHERE source_id IN "
        "('xinhua','moedict','guji','zdic')").fetchone()[0]
    con.close()

    print(f"[3] integrity {integrity}   foreign_key {'clean' if not fk else fk}")
    ok &= integrity == "ok" and not fk
    print(f"[4] forbidden tables in release: {leaked or 'none'}")
    print(f"    senses from unlicensed sources: {bad_sources}")
    ok &= not leaked and bad_sources == 0
    print(f"[5] counts {counts}  schema {schema}")
    ok &= counts == record["counts"] and schema == record["schema_version"]
    print(f"    fts_zh covers entries: {counts['fts_zh'] == counts['entries']}")
    ok &= counts["fts_zh"] == counts["entries"]

    # 6. client constant
    dart_text = DART.read_text(encoding="utf-8")
    constant_ok = record["asset_version"] in dart_text
    print(f"[6] client assetVersion {record['asset_version']} present: {constant_ok}")
    ok &= constant_ok

    print("\nASSET CHAIN VERIFIED" if ok else "\nVERIFICATION FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
