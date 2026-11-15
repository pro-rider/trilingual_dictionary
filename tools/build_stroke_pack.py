"""Build the bundled stroke pack from hanzi-writer-data.

One command, one output set:

    assets/strokes/strokes.bin.gz          the data (one JSON object per line, gzipped)
    assets/strokes/strokes.index.json      index: char -> [byte offset, byte length] + radicals + disputed
    assets/strokes/strokes.source_counts.json   stroke counts as the SOURCE gives them
    assets/strokes/build_info.json         build date, checksum, conversion statement
    assets/strokes/ARPHICPL.TXT            the licence, unaltered
    assets/strokes/README.md               generated provenance record
    lib/features/character/stroke_build_info.dart   the same build date for the Credits screen

The scope is a single number:

    python tools/build_stroke_pack.py              # top-1000 words (default)
    python tools/build_stroke_pack.py --top 3000   # the next band
    python tools/build_stroke_pack.py --top 3000 --out stroke_work/top3000 --no-review

Selection: every character of every headword in the band, simplified and
traditional. Nothing is invented: a character without source data stays absent,
and the app falls back for it.

What this tool does NOT do: it never edits the source data. If a character's
stroke count looks wrong, that is recorded in review/stroke_differences.csv for a
human decision; the only thing the tool can do about it is mark the character
`disputed` in the index so the UI stops printing an unreviewed count.

Licence: stroke data under the Arphic Public License (see docs/LICENSE-ARPHIC.md).
Reads only: the dictionary is opened with mode=ro and never written.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import random
import shutil
import sqlite3
import time
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "backend" / "data" / "build" / "dictionary.sqlite"
SRC = REPO / "stroke_work" / "package"          # unpacked npm tarball
UNIHAN_IRG = REPO / "stroke_work" / "unihan" / "Unihan_IRGSources.txt"
UNICODE_DATA = REPO / "stroke_work" / "UnicodeData.txt"
ASSETS = REPO / "assets" / "strokes"
REVIEW_DIR = REPO / "review"
LICENCE_SRC = SRC / "ARPHICPL.TXT"
BUILD_INFO_DART = REPO / "lib" / "features" / "character" / "stroke_build_info.dart"

TOP_WORDS = 1000          # <-- the one knob
COORD_DECIMALS = 1        # 1024-unit em square; 1 decimal is sub-pixel at 96 px
PACK_VERSION = 2
SOURCE_PACKAGE = "hanzi-writer-data@2.0.1"
SOURCE_SHA256 = "72baf3d82b114e60d6e40ea05f24d2262a05cd39d544e2f322ba2fceb7beff15"
SAMPLE_SEED = 20261115
WALK_RADICAL = 162        # 辶 / 辵


# --------------------------------------------------------------------------- #
# inputs
# --------------------------------------------------------------------------- #
def headwords(top: int) -> list[tuple[str, str, int]]:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT simplified, traditional, freq_rank FROM entries "
            "WHERE freq_rank IS NOT NULL AND freq_rank <= ? "
            "ORDER BY freq_rank",
            (top,),
        ).fetchall()
    finally:
        con.close()
    return rows


def is_han(char: str) -> bool:
    """True for CJK ideographs. Latin letters, digits and punctuation are not."""
    name = unicodedata.name(char, "")
    return name.startswith("CJK UNIFIED IDEOGRAPH") or name.startswith(
        "CJK COMPATIBILITY IDEOGRAPH")


def wanted_chars(rows: list[tuple[str, str, int]]) -> set[str]:
    chars: set[str] = set()
    for simp, trad, _ in rows:
        for form in (simp, trad):
            if form:
                chars.update(form)
    return chars


def load_stroke_json(ch: str) -> dict | None:
    path = SRC / f"{ch}.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def slim(record: dict) -> dict:
    """Keep the SVG outline, the median polyline and radical stroke indices."""
    def round_pts(points: list[list[float]]) -> list[list[float]]:
        return [[round(p[0], COORD_DECIMALS), round(p[1], COORD_DECIMALS)]
                for p in points]

    out = {
        "s": list(record["strokes"]),
        "m": [round_pts(median) for median in record["medians"]],
    }
    if record.get("radStrokes"):
        out["r"] = record["radStrokes"]
    return out


def unihan_total_strokes() -> dict[str, list[int]]:
    """kTotalStrokes, every value the field carries (Unihan 18 gives one here)."""
    values: dict[str, list[int]] = {}
    if not UNIHAN_IRG.exists():
        return values
    with UNIHAN_IRG.open(encoding="utf-8") as handle:
        for line in handle:
            if "kTotalStrokes" not in line:
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            numbers = [int(token) for token in parts[2].split() if token.isdigit()]
            if numbers:
                values[chr(int(parts[0][2:], 16))] = numbers
    return values


def unihan_radicals() -> dict[str, int]:
    """kRSUnicode -> Kangxi radical number per character."""
    radicals: dict[str, int] = {}
    if not UNIHAN_IRG.exists():
        return radicals
    with UNIHAN_IRG.open(encoding="utf-8") as handle:
        for line in handle:
            if "kRSUnicode" not in line:
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            value = parts[2].split()[0].split("'")[0]
            head = value.split(".")[0]
            if not head.lstrip("-").isdigit():
                continue
            number = abs(int(head))
            if 1 <= number <= 214:
                radicals[chr(int(parts[0][2:], 16))] = number
    return radicals


def kangxi_names() -> tuple[dict[int, str], dict[int, str]]:
    """Official English radical names and their unified ideographs."""
    names: dict[int, str] = {}
    unified: dict[int, str] = {}
    if not UNICODE_DATA.exists():
        return names, unified
    with UNICODE_DATA.open(encoding="utf-8") as handle:
        for line in handle:
            parts = line.split(";")
            if len(parts) < 6 or not parts[1].startswith("KANGXI RADICAL "):
                continue
            code = int(parts[0], 16)
            index = code - 0x2F00 + 1
            if not 1 <= index <= 214:
                continue
            names[index] = parts[1].removeprefix("KANGXI RADICAL ").lower()
            decomposition = parts[5].strip()
            if decomposition.startswith("<compat>"):
                hexcode = decomposition.removeprefix("<compat>").strip()
                if hexcode:
                    unified[index] = chr(int(hexcode, 16))
    return names, unified


def today() -> str:
    return time.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# rankings per character (for review files)
# --------------------------------------------------------------------------- #
def char_ranks(rows: list[tuple[str, str, int]], chars: set[str]) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for simp, trad, rank in rows:
        for form in (simp or "", trad or ""):
            for ch in form:
                if ch in chars:
                    ranks[ch] = min(ranks.get(ch, rank), rank)
    return ranks


def char_words(rows: list[tuple[str, str, int]], cn: str) -> list[str]:
    seen: list[str] = []
    for simp, trad, _ in rows:
        for form in (simp or "", trad or ""):
            if cn in form and form not in seen:
                seen.append(form)
    return seen


def simplified_or_traditional(rows: list[tuple[str, str, int]], cn: str) -> str:
    in_simp = any(cn in (simp or "") for simp, _, _ in rows)
    in_trad = any(cn in (trad or "") for _, trad, _ in rows)
    if in_simp and in_trad:
        return "both"
    if in_trad:
        return "traditional"
    return "simplified"


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #
def write_licence(out_dir: Path) -> None:
    if not LICENCE_SRC.exists():
        raise SystemExit(f"licence file missing in the package: {LICENCE_SRC}")
    shutil.copyfile(LICENCE_SRC, out_dir / "ARPHICPL.TXT")


def write_pack(
    out_dir: Path,
    chars: dict[str, dict],
    source_counts: dict[str, list[int]],
    radicals: dict[str, int],
    names: dict[int, str],
    unified: dict[int, str],
    disputed: list[str],
) -> tuple[Path, Path, int]:
    payload_parts: list[bytes] = []
    offsets: dict[str, list[int]] = {}
    cursor = 0
    for ch in sorted(chars):
        # A count that drifts from the source during conversion would be a bug
        # we would ship silently, so the build refuses to continue.
        packed = (len(chars[ch]["s"]), len(chars[ch]["m"]))
        expected = tuple(source_counts[ch])
        if packed != expected:
            raise SystemExit(
                f"conversion changed {ch}: source {expected} strokes, pack {packed}")
        line = json.dumps({ch: chars[ch]}, ensure_ascii=False, separators=(",", ":"))
        encoded = line.encode("utf-8")
        offsets[ch] = [cursor, len(encoded)]
        payload_parts.append(encoded)
        cursor += len(encoded) + 1
    raw = b"\n".join(payload_parts)

    pack = out_dir / "strokes.bin.gz"
    with gzip.GzipFile(filename="", mode="wb", fileobj=pack.open("wb"), mtime=0) as gz:
        gz.write(raw)

    radical_of = {ch: radicals[ch] for ch in chars if ch in radicals}
    radical_names = {str(n): names[n] for n in sorted(set(radical_of.values())) if n in names}
    radical_chars = {str(n): unified[n] for n in sorted(set(radical_of.values())) if n in unified}

    index = {
        "version": PACK_VERSION,
        "topWords": TOP_WORDS,
        "chars": len(offsets),
        "payload": "strokes.bin.gz",
        "payloadSha256": hashlib.sha256(pack.read_bytes()).hexdigest(),
        "rawBytes": len(raw),
        "licence": "ARPHICPL.TXT",
        "built": today(),
        "source": SOURCE_PACKAGE,
        "sourceSha256": SOURCE_SHA256,
        "entries": offsets,
        "radicalOf": radical_of,
        "radicalNames": radical_names,
        "radicalChars": radical_chars,
        # Characters whose stroke count disagrees with Unihan and whose decision
        # is still open. The UI draws them but does not print a count.
        "disputed": sorted(disputed),
    }
    index_path = out_dir / "strokes.index.json"
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8")

    (out_dir / "strokes.source_counts.json").write_text(
        json.dumps(source_counts, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8")
    return pack, index_path, len(raw)


def conversion_statement() -> str:
    return (
        "per-character JSON (strokes, medians, radStrokes) reduced to the keys "
        "s (stroke outlines), m (stroke medians) and r (radical stroke indices), "
        f"coordinates rounded to {COORD_DECIMALS} decimal, one JSON object per line, "
        "concatenated and gzipped. No character was added, changed or invented."
    )


def write_build_info(out_dir: Path, index: dict, pack: Path) -> None:
    info = {
        "built": index["built"],
        "topWords": index["topWords"],
        "chars": index["chars"],
        "payloadSha256": index["payloadSha256"],
        "gzippedBytes": pack.stat().st_size,
        "source": SOURCE_PACKAGE,
        "sourceSha256": SOURCE_SHA256,
        "conversion": conversion_statement(),
    }
    (out_dir / "build_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    # The Credits screen must not hard-code a date that drifts on rebuild, so it
    # reads this generated constant and a test fails if the two disagree.
    if out_dir.resolve() == ASSETS.resolve():
        BUILD_INFO_DART.parent.mkdir(parents=True, exist_ok=True)
        BUILD_INFO_DART.write_text(
            "// GENERATED by tools/build_stroke_pack.py — do not edit.\n"
            "//\n"
            "// The Credits screen quotes this date; test/stroke_license_audit_test.dart\n"
            "// fails if it ever disagrees with assets/strokes/build_info.json.\n"
            "\n"
            f"const String kStrokePackBuilt = '{info['built']}';\n"
            f"const String kStrokePackSource = '{info['source']}';\n"
            f"const int kStrokePackTopWords = {info['topWords']};\n"
            f"const int kStrokePackChars = {info['chars']};\n"
            f"const String kStrokePackSha256 = '{info['payloadSha256']}';\n",
            encoding="utf-8")


def write_readme(out_dir: Path, index: dict, pack: Path,
                 uncovered_words: list[str]) -> None:
    text = f"""# Stroke data (generated — do not edit)

Built by `tools/build_stroke_pack.py` on {index['built']} for the top
{index['topWords']} words.

- `strokes.bin.gz` — {index['chars']} characters, {index['rawBytes']} bytes raw
  ({pack.stat().st_size} bytes gzipped), sha256 {index['payloadSha256']}
- `strokes.index.json` — byte offset and length of each character's line, the
  Kangxi radical per character, and the `disputed` list
- `strokes.source_counts.json` — the stroke count the source file gives for each
  character, recorded before packing so a conversion slip cannot pass unnoticed
- `build_info.json` — the same facts for the Credits screen
- `ARPHICPL.TXT` — the licence, unaltered

Source: `{SOURCE_PACKAGE}` (npm), sha256 of the tarball `{SOURCE_SHA256}`, derived
from Make Me a Hanzi `graphics.txt`, which came from fonts by Arphic Technology
Co., Ltd.

Conversion: {conversion_statement()}

The converted data is available under the Arphic Public License — see
`docs/LICENSE-ARPHIC.md`.

Words in this band with no full coverage ({len(uncovered_words)}): {' '.join(uncovered_words) if uncovered_words else 'none'}
"""
    (out_dir / "README.md").write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# review files
# --------------------------------------------------------------------------- #
def write_difference_csv(path: Path, found: dict[str, dict], totals: dict[str, list[int]],
                         radicals: dict[str, int], rows: list[tuple[str, str, int]]) -> list[str]:
    """All characters whose pack count differs from Unihan. `difference` = pack - Unihan."""
    ranks = char_ranks(rows, set(found))
    differing: list[list[str]] = []
    disputed: list[str] = []
    for ch in sorted(found):
        packed = len(found[ch]["s"])
        values = totals.get(ch)
        if not values:
            continue
        reference = values[0]
        difference = packed - reference
        if difference == 0:
            continue
        radical = radicals.get(ch)
        group = "radical-辶" if radical == WALK_RADICAL else "other"
        if group == "radical-辶" and difference == -1:
            cause = "PRC counts 辶 as 3 strokes, Kangxi/Unihan as 4"
        elif difference == -1:
            cause = "pack one stroke below Unihan: PRC vs Kangxi component count, needs an eye"
        else:
            cause = "unclassified: needs a human decision"
        differing.append([
            ch,
            simplified_or_traditional(rows, ch),
            str(ranks.get(ch, "")),
            str(packed),
            " ".join(str(v) for v in values),
            str(difference),
            group,
            cause,
            "",
        ])
        disputed.append(ch)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "char", "simplified_or_traditional", "frequency_rank", "pack_strokes",
        "unihan_strokes_all_values", "difference", "group", "suspected_cause",
        "decision",
    ])
    writer.writerows(differing)
    path.write_text(buffer.getvalue(), encoding="utf-8")
    return disputed


def write_spot_check_csv(path: Path, found: dict[str, dict], totals: dict[str, list[int]],
                         rows: list[tuple[str, str, int]], differing: list[str]) -> int:
    """100 most frequent + 50 random (seed recorded) + every differing character."""
    ranks = char_ranks(rows, set(found))
    by_rank = sorted(found, key=lambda c: (ranks.get(c, 10**9), c))
    top100 = by_rank[:100]

    pool = sorted(set(found) - set(top100) - set(differing))
    rng = random.Random(SAMPLE_SEED)
    random50 = rng.sample(pool, min(50, len(pool)))

    picked: list[str] = []
    for ch in top100 + random50 + differing:
        if ch not in picked:
            picked.append(ch)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "char", "pack_strokes", "reference_strokes", "reference",
        "difference_note", "decision", "order_reference",
    ])
    for ch in picked:
        packed = len(found[ch]["s"])
        values = totals.get(ch)
        reference = values[0] if values else ""
        if not values:
            note = "not in Unihan"
        elif packed == reference:
            note = "agree on stroke count"
        else:
            note = f"count differs: pack {packed} vs Unihan {reference} ({packed - reference})"
        writer.writerow([
            ch, str(packed), str(reference),
            "Unicode Unihan 18.0.0 kTotalStrokes (counts only, no order)",
            note, "",
            "none available offline: no verified independent source for stroke ORDER "
            "(Unihan gives counts only), so this column is intentionally empty",
        ])
    path.write_text(buffer.getvalue(), encoding="utf-8")
    return len(picked)


def write_missing_csv(path: Path, absent: list[str], rows: list[tuple[str, str, int]],
                      total_wanted: int) -> tuple[int, int]:
    """Missing characters, with the words they block. Non-Han letters are skipped."""
    han_absent = [c for c in absent if is_han(c)]
    skipped = [c for c in absent if not is_han(c)]
    ranks = char_ranks(rows, set(han_absent))
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "character", "reason", "frequency_rank", "words_containing_it",
        "in_top500", "in_top1000", "han",
    ])
    for ch in han_absent:
        rank = ranks.get(ch)
        writer.writerow([
            ch,
            "no stroke data in " + SOURCE_PACKAGE,
            "" if rank is None else str(rank),
            " / ".join(char_words(rows, ch)),
            "yes" if rank is not None and rank <= 500 else "no",
            "yes" if rank is not None and rank <= 1000 else "no",
            "yes",
        ])
    for ch in skipped:
        writer.writerow([ch, "not a Han character: skipped, not missing", "", "", "", "", "no"])
    path.write_text(buffer.getvalue(), encoding="utf-8")
    return len(han_absent), len(skipped)


# --------------------------------------------------------------------------- #
def main() -> int:
    global TOP_WORDS
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=TOP_WORDS)
    parser.add_argument("--out", default=str(ASSETS))
    parser.add_argument("--no-review", action="store_true")
    args = parser.parse_args()
    TOP_WORDS = args.top
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = headwords(TOP_WORDS)
    chars_wanted = wanted_chars(rows)

    found: dict[str, dict] = {}
    source_counts: dict[str, list[int]] = {}
    absent: list[str] = []
    for ch in sorted(chars_wanted):
        record = load_stroke_json(ch)
        if record is None:
            absent.append(ch)
            continue
        found[ch] = slim(record)
        source_counts[ch] = [len(record["strokes"]), len(record["medians"])]

    t0 = time.perf_counter()
    names, unified = kangxi_names()
    radicals = unihan_radicals()
    totals = unihan_total_strokes()

    disputed: list[str] = []
    if not args.no_review and out_dir == ASSETS.resolve():
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        disputed = write_difference_csv(
            REVIEW_DIR / "stroke_differences.csv", found, totals, radicals, rows)

    pack, index_path, raw_bytes = write_pack(
        out_dir, found, source_counts, radicals, names, unified, disputed)
    build_ms = (time.perf_counter() - t0) * 1000

    index = json.loads(index_path.read_text(encoding="utf-8"))
    write_licence(out_dir)

    # ---- coverage per word
    # Only Han characters can have stroke data, so a Latin letter in "A股" is not
    # a coverage failure. The old (stage 1) counting treated every codepoint as a
    # character; both numbers are printed so the change is visible.
    full, partial, none = [], [], []
    for simp, trad, rank in rows:
        all_chars = set(simp or "") | set(trad or "")
        missing = [c for c in all_chars if c not in found and is_han(c)]
        if not missing:
            full.append(simp)
        elif all(is_han(c) for c in all_chars) and len(missing) == len(all_chars):
            none.append(simp)
        else:
            partial.append((simp, missing))
    uncovered_words = [w for w, _ in partial] + none

    old_full = sum(
        1 for simp, trad, _ in rows
        if not [c for c in set(simp or "") | set(trad or "") if c not in found])

    write_build_info(out_dir, index, pack)
    write_readme(out_dir, index, pack, uncovered_words)

    raw = gzip.decompress(pack.read_bytes())
    t1 = time.perf_counter()
    idx = json.loads(index_path.read_text(encoding="utf-8"))
    index_load_ms = (time.perf_counter() - t1) * 1000

    sample = ["我", "的", "水", "學", "醫"]
    per_char_ms = []
    for ch in sample:
        if ch not in idx["entries"]:
            continue
        off, length = idx["entries"][ch]
        t2 = time.perf_counter()
        obj = json.loads(raw[off:off + length].decode("utf-8"))
        per_char_ms.append((ch, (time.perf_counter() - t2) * 1000, len(obj[ch]["s"])))

    print(f"top words                 {TOP_WORDS}  (rows with freq_rank: {len(rows)})")
    print(f"distinct characters       {len(chars_wanted)} wanted, {len(found)} packed, {len(absent)} absent")
    print(f"absent characters         {' '.join(absent) if absent else 'none'}")
    print(f"raw payload               {raw_bytes} bytes")
    print(f"gzipped pack              {pack.stat().st_size} bytes  ({(pack.stat().st_size/1024):.1f} KB)")
    print(f"index file                {index_path.stat().st_size} bytes")
    print(f"build wall time           {build_ms:.0f} ms")
    print(f"index cold load (python)  {index_load_ms:.1f} ms")
    print("single character load     " + ", ".join(
        f"{ch} {ms:.2f} ms ({strokes} strokes)" for ch, ms, strokes in per_char_ms))
    print(f"words fully covered       {len(full)}/{len(rows)}  ({100*len(full)/max(len(rows),1):.1f}%)"
          f"   [stage-1 counting, letters included: {old_full}/{len(rows)}"
          f"  ({100*old_full/max(len(rows),1):.1f}%)]")
    print(f"words with some missing   {len(partial)}")
    print(f"words with none           {len(none)}")
    print(f"disputed characters       {len(disputed)} ({' '.join(disputed[:10])}{' ...' if len(disputed) > 10 else ''})")

    checked = sum(1 for ch in found if ch in totals)
    mismatches = [ch for ch in found
                  if ch in totals and len(found[ch]["s"]) != totals[ch][0]]
    print(f"stroke-count check        {checked} compared against Unihan kTotalStrokes, "
          f"{len(mismatches)} differ (difference = pack - Unihan)")

    if not args.no_review and out_dir == ASSETS.resolve():
        differing = [row[0] for row in csv.reader(
            (REVIEW_DIR / "stroke_differences.csv").read_text(encoding="utf-8").splitlines())][1:]
        n_spot = write_spot_check_csv(
            REVIEW_DIR / "stroke_spot_check.csv", found, totals, rows, differing)
        han_absent, skipped = write_missing_csv(
            REVIEW_DIR / "stroke_missing.csv", absent, rows, len(chars_wanted))
        print(f"review files              stroke_differences.csv ({len(differing)} rows), "
              f"stroke_spot_check.csv ({n_spot} rows), stroke_missing.csv "
              f"({han_absent} Han missing, {skipped} non-Han skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
