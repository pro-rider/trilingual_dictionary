"""The shipped database and the app's extract-once stamp must agree.

`OfflineDictionary` only re-extracts `assets/data/dictionary.sqlite.gz` when the
on-device `.stamp` differs from its `assetVersion` constant. If the asset is
rebuilt without that constant moving, every installed phone keeps the database
it extracted the first time — which is exactly how a repaired Nepali gloss
stayed invisible on a real device (device hash 79e03599…, pinned e1118fb3…).

`pack_asset.py` writes both sides together; this test fails when they drift.
It is skipped when the 43 MB gz is absent (it is gitignored, so a clean clone
and CI only ever see the selftest).
"""

import gzip
import hashlib
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
GZ = ROOT / "assets" / "data" / "dictionary.sqlite.gz"
DART = ROOT / "lib" / "data" / "local" / "offline_dictionary.dart"
VERSION_RE = re.compile(r"static const String assetVersion = '([^']*)';")


def _db_sha256() -> str:
    h = hashlib.sha256()
    with gzip.open(GZ, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _declared_version() -> str:
    match = VERSION_RE.search(DART.read_text(encoding="utf-8"))
    assert match is not None, "assetVersion constant missing from offline_dictionary.dart"
    return match.group(1)


@pytest.mark.skipif(not GZ.exists(), reason="bundled dictionary asset not present")
def test_asset_version_matches_shipped_database():
    sha = _db_sha256()
    assert _declared_version() == f"db-{sha[:10]}", (
        "assetVersion is stale: run backend/tools/pack_asset.py, then rebuild the APK"
    )


def test_version_is_content_derived_not_a_date():
    version = _declared_version().strip()
    assert version.startswith("db-"), f"unexpected assetVersion {version!r}"
    assert len(version) == len("db-") + 10, f"unexpected assetVersion {version!r}"
