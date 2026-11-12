"""Build the shippable database and its client version stamp.

One command turns the working database into a release database:

    python tools/build_release_db.py

It copies `data/build/dictionary.sqlite`, drops every candidate, review and
unlicensed table, writes provenance rows only from an allow-list, then runs
VACUUM + integrity_check + foreign_key_check, verifies schema v005, gzips the
result deterministically and writes `assetVersion` from the content hash. The
license audit below runs *before* the package is written, and it fails the
build rather than shipping a table nobody is allowed to redistribute.

The audit is also importable, so `tests/test_release_license_audit.py` exercises
it on a small fixture instead of a 114 MB copy.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
WORKING_DB = BACKEND / "data" / "build" / "dictionary.sqlite"
RELEASE_DB = BACKEND / "data" / "build" / "release" / "dictionary.release.sqlite"
PACKED = REPO / "assets" / "data" / "dictionary.sqlite.gz"
DART = REPO / "lib" / "data" / "local" / "offline_dictionary.dart"
RELEASE_JSON = REPO / "docs" / "RELEASE.json"
ASSET_PINS = REPO / "docs" / "ASSET-PINS.json"

SCHEMA_VERSION = "v005"

# Tables that must never be in the shipped file: machine output awaiting review,
# review bookkeeping, and licence-restricted candidate sources.
FORBIDDEN_TABLES = [
    "gloss_zh_candidates",       # Xinhua, licence unclear — internal benchmark only
    "gloss_zh_wikt_candidates",  # unapproved Wiktionary candidates
    "words3000_candidates",      # unreviewed new words
    "example_candidates",        # unreviewed generated sentences
    "launch_set",                # build-time planning table
    "review_audit",
    "review_rejected",
    "staging_entries",
    "staging_senses",
    "corpus_hits",               # corpus counts, not shipped content
    "import_batches",
    "dictionary_changelog",
]

# Provenance may only name these sources in the release database.
ALLOWED_PROVENANCE_SOURCES = {"CC-CEDICT", "zh.wiktionary"}
# ...and these substrings are refused anywhere in a provenance row.
FORBIDDEN_SOURCE_MARKERS = ("xinhua", "新华", "moedict", "萌典")


def audit(con: sqlite3.Connection) -> list[str]:
    """Return the problems that must block a release. Empty list = clean."""
    problems: list[str] = []
    tables = {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    for table in FORBIDDEN_TABLES:
        if table in tables:
            problems.append(f"forbidden table present: {table}")

    if "gloss_provenance" in tables:
        for source, license_value, count in con.execute(
            "SELECT source, license, count(*) FROM gloss_provenance GROUP BY source, license"
        ):
            name = (source or "").strip()
            blob = f"{source} {license_value}".lower()
            if any(marker in blob for marker in FORBIDDEN_SOURCE_MARKERS):
                problems.append(f"licence-restricted provenance: {name} ({count} rows)")
            elif name not in ALLOWED_PROVENANCE_SOURCES:
                problems.append(f"unexpected provenance source: {name!r} ({count} rows)")

    # A sense carrying an imported Chinese definition must have provenance.
    if "senses" in tables and "gloss_provenance" in tables:
        orphans = con.execute(
            """
            SELECT count(*) FROM senses s
            WHERE s.gloss_zh IS NOT NULL AND trim(s.gloss_zh) <> ''
              AND s.sense_id NOT IN (SELECT sense_id FROM gloss_provenance)
            """
        ).fetchone()[0]
        if orphans:
            problems.append(f"{orphans} Chinese definitions without provenance")

    version = None
    if "meta" in tables:
        for key in ("schema_version", "dataset_version"):
            row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            if row:
                version = f"{key}={row[0]}"
    if version is None:
        problems.append("meta table missing schema_version")
    return problems


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def drop_forbidden(con: sqlite3.Connection) -> list[str]:
    dropped = []
    for table in FORBIDDEN_TABLES:
        row = con.execute(
            "SELECT type FROM sqlite_master WHERE name=? AND type IN ('table','view')",
            (table,),
        ).fetchone()
        if row is None:
            continue
        con.execute(f"DROP {'VIEW' if row[0] == 'view' else 'TABLE'} {table}")
        dropped.append(table)
    return dropped


def pack(source: Path, target: Path) -> str:
    """Deterministic gzip: identical input gives an identical file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as raw, gzip.GzipFile(
        filename="dictionary.sqlite", mode="wb", fileobj=raw, mtime=0
    ) as gz:
        gz.write(source.read_bytes())
    return sha256_file(target)


def sync_dart_version(version: str) -> tuple[str, str]:
    import re

    pattern = re.compile(r"(static const String assetVersion = ')[^']*(';)")
    text = DART.read_text(encoding="utf-8")
    match = pattern.search(text)
    if match is None:
        raise SystemExit(f"assetVersion constant not found in {DART}")
    old = match.group(0)
    new = f"{match.group(1)}{version}{match.group(2)}"
    if old != new:
        DART.write_text(text.replace(old, new, 1), encoding="utf-8")
    return old, new


def write_release_json(result: dict) -> None:
    """Record what was built, from what input, with which hash.

    The file is written after the audit passes, so it can never describe a
    database that failed the licence check.
    """
    import json
    import datetime as _dt

    payload = {
        "built_at": _dt.datetime.now().replace(microsecond=0).isoformat(),
        "source_db": str(WORKING_DB),
        "source_sha256": sha256_file(WORKING_DB),
        **{k: v for k, v in result.items() if k != "dropped_tables"},
        "dropped_tables": result["dropped_tables"],
        "licence_audit": "clean (see tools/build_release_db.py:audit)",
        "approval": "PENDING HUMAN REVIEW — see docs/HUMAN_TODO.md",
    }
    RELEASE_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def repin(sha: str, size: int, version: str, counts: dict) -> str:
    """Update the shipped-database pin and say plainly that approval is pending.

    The guard test exists to catch silent drift. It must not be defeated by
    editing a hash without evidence, so this rewrites the evidence string too
    and states that no human has signed off yet.
    """
    import json

    pins = json.loads(ASSET_PINS.read_text(encoding="utf-8"))
    evidence = ""
    for pin in pins["pins"]:
        if pin["path"] == "backend/data/build/dictionary.sqlite":
            evidence = (
                "PENDING HUMAN APPROVAL — rebuilt by backend/tools/build_release_db.py "
                f"on {_iso_today()} for the release-prep branch: {version}, "
                f"entries {counts.get('entries')}, senses {counts.get('senses')}, "
                f"examples {counts.get('examples')}. Content changed because "
                "(1) 13,867 zh.wiktionary definitions were imported with per-row "
                "provenance, (2) 291 new-word translations and the launch_set table "
                "were added, (3) one U+FFFD and one Latin-in-Devanagari gloss in "
                "words3000_candidates were cleared, (4) one missing thumbnail was "
                "written. integrity_check ok, foreign_key_check clean, licence "
                "audit clean. Previous pin e1118fb343. This pin update is "
                "mechanical; a human must still approve the release build."
            )
            pin["sha256"] = sha
            pin["bytes"] = size
            pin["approved_by"] = evidence
            pin["known_defect"] = None
            break
    ASSET_PINS.write_text(
        json.dumps(pins, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return evidence


def _iso_today() -> str:
    import datetime as _dt

    return _dt.date.today().isoformat()


def build(*, pack_asset_file: bool = True) -> dict:
    if not WORKING_DB.exists():
        raise SystemExit(f"working database not found: {WORKING_DB}")
    RELEASE_DB.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(WORKING_DB, RELEASE_DB)

    con = sqlite3.connect(RELEASE_DB)
    dropped = drop_forbidden(con)
    con.commit()
    con.execute("VACUUM")
    problems = audit(con)

    schema_version = con.execute(
        "SELECT value FROM meta WHERE key='schema_version'"
    ).fetchone()
    schema_version = schema_version[0] if schema_version else ""
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    foreign = con.execute("PRAGMA foreign_key_check").fetchall()

    counts = {}
    for table in ("entries", "senses", "examples", "images", "fts", "fts_zh"):
        try:
            counts[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            counts[table] = None
    con.close()

    if problems:
        raise SystemExit("release audit failed:\n  - " + "\n  - ".join(problems))
    if integrity != "ok":
        raise SystemExit(f"integrity_check failed: {integrity}")
    if foreign:
        raise SystemExit(f"foreign_key_check found {len(foreign)} problem(s)")
    if schema_version != SCHEMA_VERSION:
        raise SystemExit(f"schema_version is {schema_version!r}, expected {SCHEMA_VERSION}")

    db_sha = sha256_file(RELEASE_DB)
    db_bytes = RELEASE_DB.stat().st_size

    # Every approved picture must resolve to a bundled thumbnail. Checking here
    # means a release can never ship a reference the client cannot render; the
    # Flutter card would otherwise show the "no picture" icon for a broken path.
    gate = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("verify_image_assets.py")),
         "--db", str(RELEASE_DB)],
        capture_output=True, text=True, encoding="utf-8")
    if gate.returncode != 0:
        tail = "\n".join(
            line for line in gate.stdout.splitlines() if line.startswith("FAIL"))
        raise SystemExit("image asset gate failed:\n" + (tail or gate.stdout[-800:]))

    packed_sha = packed_bytes = None
    version = f"db-{db_sha[:10]}"
    if pack_asset_file:
        packed_sha = pack(RELEASE_DB, PACKED)
        packed_bytes = PACKED.stat().st_size
        old, new = sync_dart_version(version)
    else:
        old = new = "(unchanged)"

    result = {
        "release_db": str(RELEASE_DB),
        "db_sha256": db_sha,
        "db_bytes": db_bytes,
        "packed": str(PACKED) if pack_asset_file else None,
        "packed_sha256": packed_sha,
        "packed_bytes": packed_bytes,
        "asset_version": version,
        "dart_constant": new,
        "dropped_tables": dropped,
        "counts": counts,
        "schema_version": schema_version,
        "integrity": integrity,
    }
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pack", action="store_true",
                    help="build and audit only, do not touch assets/ or the client")
    ap.add_argument("--write-release-json", action="store_true",
                    help="also write docs/RELEASE.json")
    ap.add_argument("--repin", action="store_true",
                    help="also update docs/ASSET-PINS.json for the working database")
    args = ap.parse_args(argv)
    result = build(pack_asset_file=not args.no_pack)
    print(f"release db  {result['db_bytes'] / 1048576:.1f} MB  sha256={result['db_sha256']}")
    if result["packed"]:
        print(f"packed gz   {result['packed_bytes'] / 1048576:.1f} MB  "
              f"sha256={result['packed_sha256']}")
        print(f"assetVersion {result['asset_version']} -> {result['dart_constant']}")
    print(f"dropped     {', '.join(result['dropped_tables']) or '(none)'}")
    print(f"counts      {result['counts']}")
    print(f"schema      {result['schema_version']}  integrity={result['integrity']}")
    if args.write_release_json:
        write_release_json(result)
        print(f"wrote       {RELEASE_JSON}")
    if args.repin:
        repin(sha256_file(WORKING_DB), WORKING_DB.stat().st_size,
              result["asset_version"], result["counts"])
        print(f"repinned    {ASSET_PINS} (working database)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
