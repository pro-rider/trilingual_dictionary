"""Rebuild `assets/data/dictionary.sqlite.gz` deterministically.

mtime=0 and a fixed inner filename keep the gzip byte-identical for identical
input, so a rebuild does not look like a data change to git or to the app.

The Flutter app only re-extracts the shipped database when the on-device
`.stamp` sidecar differs from `OfflineDictionary.assetVersion`
(`lib/data/local/offline_dictionary.dart`). A stale constant therefore pins
every phone to the database it first extracted, no matter how often the asset
is rebuilt. This script is the single place that keeps the two in sync: after
writing the gz it rewrites the constant to a content-derived value, so a
rebuild always reaches installed devices.
"""

import gzip
import hashlib
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "build" / "dictionary.sqlite"
DST = ROOT.parent / "assets" / "data" / "dictionary.sqlite.gz"
DART = ROOT.parent / "lib" / "data" / "local" / "offline_dictionary.dart"

VERSION_RE = re.compile(r"(static const String assetVersion = ')[^']*(';)")


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def asset_version(db_sha: str) -> str:
    """Content-derived stamp: identical input -> identical version string."""
    return f"db-{db_sha[:10]}"


def sync_dart_version(version: str) -> tuple[str, str]:
    text = DART.read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if match is None:
        raise SystemExit(f"assetVersion constant not found in {DART}")
    old = match.group(0)
    new = f"{match.group(1)}{version}{match.group(2)}"
    if old != new:
        DART.write_text(text.replace(old, new, 1), encoding="utf-8")
    return old, new


def main() -> int:
    data = SRC.read_bytes()
    db_sha = hashlib.sha256(data).hexdigest()
    print(f"src  {SRC.stat().st_size / 1048576:.2f} MB sha256={db_sha}")
    DST.parent.mkdir(parents=True, exist_ok=True)
    with open(DST, "wb") as raw, gzip.GzipFile(
        filename="dictionary.sqlite", mode="wb", fileobj=raw, mtime=0
    ) as gz:
        gz.write(data)
    gz_sha = sha256_file(DST)
    print(f"gz   {DST.stat().st_size / 1048576:.2f} MB sha256={gz_sha} -> {DST}")

    version = asset_version(db_sha)
    old, new = sync_dart_version(version)
    print(f"dart {DART.name}: {old} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
