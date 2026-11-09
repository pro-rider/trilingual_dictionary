"""Phase 1 — read-only audit of the Nepali data in dictionary.sqlite.

Opens the database with ``mode=ro`` so it cannot modify anything, classifies
every non-empty Nepali value, and reports coverage by HSK level, frequency
band, category and part of speech.

Console output is ASCII only (Windows console code pages mangle Devanagari);
the full findings go to the markdown report.

Usage:
    python backend/tools/audit_ne_quality.py [--db PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(BACKEND, "data", "build", "dictionary.sqlite")
DEFAULT_OUT = os.path.join(os.path.dirname(BACKEND), "docs", "PHASE1-AUDIT.md")

DEV = re.compile(r"[\u0900-\u097F]")          # Devanagari block
CJK = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")
Latin = re.compile(r"[A-Za-z]")
DIGIT = re.compile(r"[0-9\u0966-\u096F]")     # ASCII and Devanagari digits

PLACEHOLDERS = {
    "translate now", "translation pending", "n/a", "na", "todo", "tbd",
    "none", "null", "-", "—", "...", "?", "unknown", "xxx",
}

# Values that are legitimate as Nepali but contain Latin letters: the
# specification says flag them for script review, never reject them.
LATIN_OK_HINTS = ("http", "kg", "ml", "cm", "mm", "%", "ph", "dna", "rna",
                  "hiv", "aids", "ok", "cd", "tv", "pm", "am")


def ro_connect(path):
    uri = "file:%s?mode=ro" % path.replace("\\", "/")
    return sqlite3.connect(uri, uri=True)


def normalize(value):
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def classify(value, gloss_en):
    """Return (bucket, detail) for one Nepali value.

    Buckets, in reporting order:
      placeholder      -- a known non-value string
      copy_of_english  -- the "Nepali" text is the English gloss
      wrong_script     -- no Devanagari at all and does contain other scripts
      latin_mix        -- Devanagari plus Latin, legitimate-or-not: needs review
      digits           -- Devanagari plus digits
      ok               -- Devanagari only
    """
    v = (value or "").strip()
    n = normalize(v)
    if n in PLACEHOLDERS:
        return "placeholder", v
    gl = normalize(gloss_en)
    if gl and n == gl:
        return "copy_of_english", v
    has_dev = bool(DEV.search(v))
    if not has_dev:
        if CJK.search(v):
            return "wrong_script", v
        if Latin.search(v):
            return "no_devanagari", v
        return "wrong_script", v
    if Latin.search(v):
        return "latin_mix", v
    if DIGIT.search(v):
        return "digits", v
    return "ok", v


def pct(part, whole):
    return 100.0 * part / whole if whole else 0.0


def band_of(freq):
    if freq is None:
        return "no freq rank"
    if freq <= 1000:
        return "1-1000"
    if freq <= 5000:
        return "1001-5000"
    if freq <= 20000:
        return "5001-20000"
    return "20001+"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    conn = ro_connect(args.db)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    totals = {}
    for label, sql in (
        ("entries", "select count(*) from entries"),
        ("senses", "select count(*) from senses"),
        ("senses_with_ne", "select count(*) from senses where gloss_ne is not null and trim(gloss_ne) <> ''"),
        ("senses_empty_ne", "select count(*) from senses where gloss_ne is null or trim(gloss_ne) = ''"),
        ("ne_status_values", "select count(distinct ne_status) from senses"),
        ("examples", "select count(*) from examples"),
        ("images", "select count(*) from images"),
    ):
        totals[label] = conn.execute(sql).fetchone()[0]

    status_counts = dict(
        conn.execute(
            "select coalesce(nullif(trim(ne_status),''),'(empty)'), count(*) "
            "from senses group by 1 order by 2 desc"
        ).fetchall()
    )

    # --- classification -------------------------------------------------
    buckets = collections.Counter()
    bucket_examples = collections.defaultdict(list)
    latin_examples = []
    dup_by_text = collections.defaultdict(set)   # ne text -> set of glosses

    rows = conn.execute(
        """
        select s.sense_id, s.entry_id, e.simplified, e.pinyin_plain, s.gloss_en, s.gloss_ne
        from senses s join entries e on e.entry_id = s.entry_id
        where s.gloss_ne is not null and trim(s.gloss_ne) <> ''
        """
    )
    for sense_id, entry_id, zh, py, gloss, ne in rows:
        bucket, value = classify(ne, gloss)
        buckets[bucket] += 1
        if len(bucket_examples[bucket]) < 12:
            bucket_examples[bucket].append(
                {"sense_id": sense_id, "zh": zh, "pinyin": py, "gloss_en": gloss, "ne": value}
            )
        if bucket == "latin_mix" and len(latin_examples) < 25:
            latin_examples.append(
                {"sense_id": sense_id, "zh": zh, "gloss_en": gloss, "ne": value}
            )
        if bucket in ("ok", "digits", "latin_mix"):
            dup_by_text[normalize(value)].add(normalize(gloss))

    collisions = sorted(
        ((t, g) for t, g in dup_by_text.items() if len(g) >= 2),
        key=lambda x: -len(x[1]),
    )[:40]

    # --- coverage -------------------------------------------------------
    def coverage(group_sql, group_col="grp"):
        """coverage() -> list of (group, senses, with_ne, pct)"""
        out = conn.execute(
            f"""
            select {group_sql} as grp,
                   count(*) as senses,
                   sum(case when s.gloss_ne is not null and trim(s.gloss_ne) <> '' then 1 else 0 end) as with_ne
            from senses s join entries e on e.entry_id = s.entry_id
            group by 1 order by 2 desc
            """
        ).fetchall()
        return [(g, t, w, pct(w, t)) for g, t, w in out]

    by_hsk = coverage("coalesce(cast(e.hsk_level as text), '(null)')")
    by_pos = coverage("coalesce(nullif(e.pos_primary,''), '(empty)')")
    by_category = coverage("coalesce(nullif(e.category,''), '(empty)')")[:12]

    # frequency bands are computed in Python because they are ranges
    band_rows = collections.Counter()
    band_ne = collections.Counter()
    for freq, has_ne in conn.execute(
        "select e.freq_rank, "
        "case when s.gloss_ne is not null and trim(s.gloss_ne) <> '' then 1 else 0 end "
        "from senses s join entries e on e.entry_id = s.entry_id"
    ):
        b = band_of(freq)
        band_rows[b] += 1
        band_ne[b] += has_ne
    by_band = [(b, band_rows[b], band_ne[b], pct(band_ne[b], band_rows[b]))
               for b in ("1-1000", "1001-5000", "5001-20000", "20001+", "no freq rank")]

    # duplicates: identical Nepali text for more than one sense
    ne_counts = collections.Counter(dup_by_text.keys())
    most_shared = [(t, c) for t, c in ne_counts.most_common(15)]

    # --- severity list --------------------------------------------------
    issues = []
    if totals["senses_empty_ne"]:
        issues.append(("blocker", "Missing Nepali gloss", totals["senses_empty_ne"],
                       "Every one of these shows an empty Nepali box in the app"))
    if buckets["placeholder"]:
        issues.append(("blocker", "Placeholder text in Nepali column", buckets["placeholder"],
                       "A non-value was stored where a translation belongs"))
    if buckets["copy_of_english"]:
        issues.append(("major", "Nepali value copies the English gloss", buckets["copy_of_english"],
                       "Reads as an untranslated leftover"))
    if buckets["no_devanagari"] + buckets["wrong_script"]:
        issues.append(("major", "No Devanagari in the Nepali column",
                       buckets["no_devanagari"] + buckets["wrong_script"],
                       "Wrong script; needs replacing, not just review"))
    if buckets["latin_mix"]:
        issues.append(("review", "Latin letters inside a Devanagari value", buckets["latin_mix"],
                       "Acronyms, units and scientific names are legitimate: review, do not reject"))
    if collisions:
        issues.append(("review", "Same Nepali word used for several different glosses",
                       len(collisions), "Sense-aware termbase must resolve these before reuse"))
    if by_hsk and all(g == "5" or g == "(null)" for g, *_ in by_hsk):
        issues.append(("blocker", "hsk_level is unusable",
                       sum(t for g, t, *_ in by_hsk if g == "5"),
                       "All non-null HSK values are 5, so HSK 1-3 queues are empty"))
    if by_pos and by_pos[0][0] == "(empty)":
        issues.append(("blocker", "pos_primary is empty", by_pos[0][1],
                       "No part-of-speech signal, so no concrete-noun or verb filter exists"))

    report = {
        "started": started,
        "db": args.db,
        "totals": totals,
        "ne_status": status_counts,
        "buckets": dict(buckets),
        "coverage_hsk": by_hsk,
        "coverage_pos": by_pos,
        "coverage_category": by_category,
        "coverage_band": by_band,
        "collisions": collisions[:20],
        "most_shared_ne": most_shared,
        "issues": issues,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# Phase 1 audit — Nepali data quality and coverage\n\n")
        f.write("Read-only pass over `%s` at %s.\n\n" % (args.db, started))
        f.write("## Totals\n\n| Item | Count |\n|---|---|\n")
        for k, v in totals.items():
            f.write("| %s | %d |\n" % (k, v))
        f.write("\n`ne_status` values: ")
        f.write(", ".join("`%s` %d" % (k, v) for k, v in status_counts.items()) or "(none)")
        f.write("\n\n## Classification of the %d non-empty Nepali values\n\n" % totals["senses_with_ne"])
        f.write("| Bucket | Count | Share |\n|---|---|---|\n")
        for b in ("ok", "latin_mix", "digits", "copy_of_english", "placeholder", "no_devanagari", "wrong_script"):
            if buckets[b]:
                f.write("| %s | %d | %.1f%% |\n" % (b, buckets[b], pct(buckets[b], totals["senses_with_ne"])))
        f.write("\nBuckets: `ok` = Devanagari only; `latin_mix` = legitimate-looking Nepali with "
                "Latin letters (acronyms, units, scientific names) — review, do not reject; "
                "`digits` = Devanagari plus numerals; `copy_of_english` = the gloss repeated; "
                "`placeholder` = a known non-value; `no_devanagari`/`wrong_script` = cannot be Nepali.\n")

        for b in ("placeholder", "copy_of_english", "no_devanagari", "wrong_script", "latin_mix", "digits"):
            ex = bucket_examples.get(b) or []
            if not ex:
                continue
            f.write("\n### Examples — %s\n\n" % b)
            f.write("| sense_id | word | pinyin | English gloss | Nepali value |\n|---|---|---|---|---|\n")
            for e in ex:
                f.write("| %d | %s | %s | %s | %s |\n" % (
                    e["sense_id"], e["zh"], e["pinyin"], e["gloss_en"], e["ne"]))

        f.write("\n## Coverage by HSK level\n\n| hsk_level | senses | with Nepali | coverage |\n|---|---|---|---|\n")
        for g, t, w, p in by_hsk:
            f.write("| %s | %d | %d | %.1f%% |\n" % (g, t, w, p))

        f.write("\n## Coverage by frequency band\n\n| band | senses | with Nepali | coverage |\n|---|---|---|---|\n")
        for b, t, w, p in by_band:
            f.write("| %s | %d | %d | %.1f%% |\n" % (b, t, w, p))

        f.write("\n## Coverage by part of speech\n\n| pos_primary | senses | with Nepali | coverage |\n|---|---|---|---|\n")
        for g, t, w, p in by_pos[:12]:
            f.write("| %s | %d | %d | %.1f%% |\n" % (g or "(empty)", t, w, p))

        f.write("\n## Coverage by domain (category, top 12)\n\n| category | senses | with Nepali | coverage |\n|---|---|---|---|\n")
        for g, t, w, p in by_category:
            f.write("| %s | %d | %d | %.1f%% |\n" % (g, t, w, p))

        if collisions:
            f.write("\n## Same Nepali word used for different glosses (top 20)\n\n")
            f.write("| Nepali (normalised) | glosses it is attached to |\n|---|---|\n")
            for text, glosses in collisions[:20]:
                f.write("| %s | %s |\n" % (text, ", ".join(sorted(glosses))))

        if latin_examples:
            f.write("\n## Latin-in-Devanagari samples (needs script review, not rejection)\n\n")
            f.write("| word | gloss | Nepali |\n|---|---|---|\n")
            for e in latin_examples:
                f.write("| %s | %s | %s |\n" % (e["zh"], e["gloss_en"], e["ne"]))

        f.write("\n## Issues, with severity\n\n| severity | issue | count | why it matters |\n|---|---|---|---|\n")
        for sev, issue, count, why in issues:
            f.write("| %s | %s | %s | %s |\n" % (sev, issue, count, why))
        f.write("\n")

    print("db            %s" % args.db)
    print("senses        %d" % totals["senses"])
    print("with ne       %d (%.1f%%)" % (totals["senses_with_ne"], pct(totals["senses_with_ne"], totals["senses"])))
    print("empty ne      %d" % totals["senses_empty_ne"])
    for b in ("ok", "latin_mix", "digits", "copy_of_english", "placeholder", "no_devanagari", "wrong_script"):
        if buckets[b]:
            print("bucket %-16s %d" % (b, buckets[b]))
    print("collisions    %d" % len(collisions))
    print("issues        %d (blockers: %d)" % (len(issues), sum(1 for i in issues if i[0] == "blocker")))
    print("report        %s" % args.out)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
