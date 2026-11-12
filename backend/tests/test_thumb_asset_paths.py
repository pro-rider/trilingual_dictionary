"""Every bundled thumbnail must live in a directory the app actually ships.

Flutter's `pubspec.yaml` asset entry for a directory is **not recursive**: listing
`assets/images/thumbs/` puts the files directly inside that folder into the APK,
and nothing from `assets/images/thumbs/ce/`. A database row pointing at a nested
path therefore resolves in the repository and fails on the device, where
`Image.asset` throws and `errorBuilder` silently swaps in a category icon.

This test encodes that rule against the real bundled database. The second test
proves the rule checker itself works, so CI keeps coverage even when the
gitignored 96 MB database is absent.
"""

import pathlib
import re
import sqlite3

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "data" / "build" / "dictionary.sqlite"
PUBSPEC = ROOT / "pubspec.yaml"
ASSETS_BLOCK = re.compile(r"^\s*assets:\s*$", re.MULTILINE)


def declared_asset_entries(text: str) -> list[str]:
    """Return the raw `flutter: assets:` entries from pubspec.yaml."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if ASSETS_BLOCK.match(line):
            start = i + 1
            break
    if start is None:
        raise AssertionError("pubspec.yaml has no flutter: assets: block")
    base_indent = len(lines[start - 1]) - len(lines[start - 1].lstrip())
    entries = []
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent and stripped.startswith(("uses-material-design", "fonts")):
            break
        if indent <= base_indent and not stripped.startswith("-"):
            break
        if stripped.startswith("- "):
            entries.append(stripped[2:].strip().strip("\"'"))
    return entries


def coverage_reason(asset: str, entries: list[str]) -> str | None:
    """None when the asset ships; otherwise the reason it does not.

    Every declared entry is considered, not just the first matching prefix:
    listing `assets/images/thumbs/ce/` as well as `assets/images/thumbs/` does
    ship `thumbs/ce/x.webp`, because Flutter takes the union of the declared
    directories. Checking only the first match would keep reporting a file as
    unbundled after it had been fixed, which is the failure mode this whole
    audit is about — a gate that stays red after the defect is gone.
    """
    normalised = asset.replace("\\", "/")
    reasons = []
    for entry in entries:
        if entry.endswith("/"):
            prefix = entry.rstrip("/") + "/"
            if normalised.startswith(prefix):
                remainder = normalised[len(prefix):]
                if "/" in remainder:
                    reasons.append(
                        f"'{entry}' declares a directory non-recursively, "
                        f"so '{remainder}' is never bundled"
                    )
                else:
                    return None
        elif normalised == entry:
            return None
    if reasons:
        return "; ".join(reasons)
    return f"not under any declared asset directory {entries}"


@pytest.mark.skipif(not DB.exists(), reason="bundled dictionary database not present")
def test_every_thumb_asset_is_shipped_in_the_apk():
    entries = declared_asset_entries(PUBSPEC.read_text(encoding="utf-8"))
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT image_id, thumb_asset FROM images "
            "WHERE thumb_asset IS NOT NULL AND thumb_asset != '' ORDER BY image_id"
        ).fetchall()
    finally:
        con.close()
    bad = []
    for image_id, asset in rows:
        reason = coverage_reason(asset, entries)
        if reason is not None:
            bad.append(f"image_id {image_id}: {asset} — {reason}")
    assert not bad, (
        "these thumbnails can never load on a device:\n" + "\n".join(bad)
    )


def test_rule_checker_rejects_nested_path_and_accepts_flat_one(tmp_path):
    pubspec = tmp_path / "pubspec.yaml"
    pubspec.write_text(
        "flutter:\n  uses-material-design: true\n  assets:\n"
        "    - assets/images/thumbs/\n    - assets/data/\n",
        encoding="utf-8",
    )
    entries = declared_asset_entries(pubspec.read_text(encoding="utf-8"))
    assert entries == ["assets/images/thumbs/", "assets/data/"]
    assert coverage_reason("assets/images/thumbs/ok.webp", entries) is None
    nested = coverage_reason("assets/images/thumbs/ce/deep.webp", entries)
    assert nested is not None and "non-recursively" in nested
    outside = coverage_reason("assets/images/other/ok.webp", entries)
    assert outside is not None and "declared asset directory" in outside
