"""Propose a variant -> standard-form map for characters missing stroke data.

Proposal only. This tool never applies anything: it writes
`review/stroke_variant_map.csv` with a blank `decision` column, and the pack is
not touched.

For every missing Han character it reads Unihan's variant fields —

    kTraditionalVariant   the traditional form(s) of a simplified character
    kSimplifiedVariant     the simplified form(s) of a traditional character
    kZVariant              other variants recorded by Unihan

— and reports each candidate plus whether that candidate actually has stroke
data in the local package. A candidate with no stroke data is useless, so it

Usage:

    python tools/propose_variants.py
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "stroke_work" / "package"
VARIANTS = REPO / "stroke_work" / "unihan" / "Unihan_Variants.txt"
ASSETS = REPO / "assets" / "strokes"
REVIEW_DIR = REPO / "review"

FIELDS = ("kTraditionalVariant", "kSimplifiedVariant", "kZVariant")


def is_han(char: str) -> bool:
    name = unicodedata.name(char, "")
    return name.startswith("CJK UNIFIED IDEOGRAPH") or name.startswith(
        "CJK COMPATIBILITY IDEOGRAPH")


def load_variants() -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    if not VARIANTS.exists():
        raise SystemExit(f"missing {VARIANTS}; download Unihan.zip and extract it")
    with VARIANTS.open(encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3 or not parts[0].startswith("U+"):
                continue
            field = parts[1]
            if field not in FIELDS:
                continue
            char = chr(int(parts[0][2:], 16))
            # A variant token may carry a source tag: "U+4E94<kMatthews".
            chars = [chr(int(token.split("<")[0][2:], 16))
                     for token in parts[2].split()
                     if token.startswith("U+")]
            out.setdefault(char, {})[field] = chars
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(REVIEW_DIR / "stroke_variant_map.csv"))
    args = parser.parse_args()

    index = json.loads((ASSETS / "strokes.index.json").read_text(encoding="utf-8"))
    counts = json.loads((ASSETS / "strokes.source_counts.json").read_text(encoding="utf-8"))
    variants = load_variants()

    missing_csv = REVIEW_DIR / "stroke_missing.csv"
    rows = list(csv.DictReader(missing_csv.read_text(encoding="utf-8").splitlines()))
    missing = [row["character"] for row in rows if row["han"] == "yes"]

    out_rows: list[list[str]] = []
    for char in missing:
        entry = variants.get(char)
        if not entry:
            out_rows.append([char, "none in Unihan_Variants", "", "", "no", "",
                             "Unihan records no variant for this character", ""])
            continue
        for field in FIELDS:
            for candidate in entry.get(field, []):
                has = candidate in index["entries"]
                packed = ""
                if has:
                    packed = str(counts[candidate][0]) if candidate in counts else ""
                out_rows.append([
                    char, field, f"U+{ord(candidate):04X}", candidate,
                    "yes" if has else "no", packed,
                    "standard-form candidate from Unihan",
                    "",
                ])

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "missing_char", "unihan_field", "candidate_code", "candidate_char",
        "candidate_has_strokes", "candidate_pack_strokes", "relation_note", "decision",
    ])
    writer.writerows(out_rows)
    Path(args.out).write_text(buffer.getvalue(), encoding="utf-8")

    with_candidate = len({row[0] for row in out_rows if row[4] == "yes"})
    without = len({row[0] for row in out_rows if row[4] == "no"})
    print(f"missing Han characters          {len(missing)}")
    print(f"rows written                    {len(out_rows)}")
    print(f"missing chars with a usable      {with_candidate} candidate that has stroke data")
    print(f"missing chars with no usable     {without}")
    for row in out_rows:
        print("  " + " | ".join(row[:6]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
