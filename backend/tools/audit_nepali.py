"""N2 — read-only audit of Nepali coverage in the dictionary.

Answers, without touching the database:
  * how many entries / senses have a Nepali meaning, and how many do not
  * how the gaps split by HSK level, frequency band, part of speech, domain
    and entry type (word / phrase / chengyu / proper noun / measure word)
  * how many unique English glosses need translating (the real workload)
  * which existing Nepali values are invalid (empty, whitespace, Latin letters,
    placeholder text, a copy of the English)

Outputs (default `backend/data/build/reports/`):
  ne_audit_missing.csv     one row per sense that still needs Nepali
  ne_audit_bad_values.csv  one row per existing Nepali value that fails a rule
  ne_audit_summary.json    all counters, machine readable
  ne_audit_summary.md      the same counters as a readable report

Usage:
  .venv\\Scripts\\python.exe tools\\audit_nepali.py
  .venv\\Scripts\\python.exe tools\\audit_nepali.py --db data\\build\\dictionary.sqlite
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

# Devanagari block + Devanagari extended; anything else in a "Nepali" field is suspect.
DEVANAGARI = re.compile(r"[\u0900-\u097F\uA8E0-\uA8FF]")
LATIN = re.compile(r"[A-Za-z]")
PLACEHOLDER = re.compile(
    r"(?i)(translate\s*now|tbd|todo|n/?a|placeholder|null|none|missing|待翻译|待补)")
# Frequency / cost model, taken from measured runs on this machine.
SENSES_PER_SEC = 0.47          # enrich_dictionary.py measured 123 senses / 262.8 s
COST_PER_SENSE_CHEAP = 0.0000131   # ≈$2.6 for 198k senses, cheap model
COST_PER_SENSE_FRONTIER = 0.000141  # ≈$28 for 198k senses, GPT-class


def is_blank(value) -> bool:
    return value is None or not str(value).strip()


def normalise_gloss(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def atomic_glosses(text: str) -> list[str]:
    """Split 'sad; sorrowful' / 'to walk / to go' into single glosses."""
    parts = re.split(r"[;；/|]", text or "")
    return [p.strip(" .。,").lower() for p in parts if p.strip(" .。,;")]


def entry_type(row: sqlite3.Row) -> str:
    if row["is_chengyu"]:
        return "chengyu"
    if row["is_classifier"]:
        return "measure_word"
    if row["is_proper"]:
        return "proper_noun"
    word = row["simplified"] or ""
    if " " in word or "-" in word or len(re.findall(r"[\u4e00-\u9fff]", word)) >= 4:
        return "phrase"
    return "word"


def freq_band(rank) -> str:
    if rank is None:
        return "unknown"
    if rank <= 5_000:
        return "1-5k"
    if rank <= 20_000:
        return "5k-20k"
    if rank <= 50_000:
        return "20k-50k"
    if rank <= 100_000:
        return "50k-100k"
    return "100k+"


def hsk_band(level) -> str:
    return f"HSK{level}" if level else "not_hsk"


def bad_reason(gloss_en: str, gloss_ne: str) -> str | None:
    """Why an existing Nepali value is not acceptable; None means it is fine."""
    ne = str(gloss_ne or "")
    if not ne.strip():
        return "empty"
    if PLACEHOLDER.search(ne):
        return "placeholder"
    if not DEVANAGARI.search(ne):
        return "no_devanagari"
    if LATIN.search(ne):
        return "latin_letters"
    if abs(len(ne) - len(gloss_en or "")) < 3 and ne.strip().lower() == (gloss_en or "").strip().lower():
        return "copy_of_english"
    if len(ne) > 120 or len(ne) < 1:
        return "bad_length"
    if unicodedata.normalize("NFC", ne) != ne:
        return "unicode_not_nfc"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(Path("data") / "build" / "dictionary.sqlite"))
    ap.add_argument("--out", default=str(Path("data") / "build" / "reports"))
    ap.add_argument("--top", type=int, nargs="*", default=[20_000, 50_000, 100_000],
                    help="frequency cohorts to price in the summary")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 2
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # read-only connection: this tool must never write
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        """
        SELECT e.entry_id, e.simplified, e.traditional, e.pinyin_marked,
               e.pos_primary, e.category, e.is_proper, e.is_chengyu,
               e.is_classifier, e.freq_rank, e.hsk_level,
               s.sense_id, s.sense_order, s.gloss_en, s.gloss_zh, s.gloss_ne,
               s.ne_status
          FROM entries e
          JOIN senses s ON s.entry_id = e.entry_id
        """
    ).fetchall()

    examples = {
        r["sense_id"]: r["en"]
        for r in con.execute(
            "SELECT sense_id, en FROM examples WHERE en IS NOT NULL AND trim(en) <> ''"
        )
    }
    con.close()

    total_senses = len(rows)
    have_ne = [r for r in rows if not is_blank(r["gloss_ne"])]
    missing = [r for r in rows if is_blank(r["gloss_ne"])]

    entry_ids_with_ne = {r["entry_id"] for r in have_ne}
    all_entry_ids = {r["entry_id"] for r in rows}

    # ---- existing values that are present but invalid ----------------------
    bad = []
    for r in have_ne:
        reason = bad_reason(r["gloss_en"], r["gloss_ne"])
        if reason:
            bad.append((r, reason))

    # ---- grouping of the gap ----------------------------------------------
    def group(key_fn) -> dict[str, dict[str, int]]:
        out = defaultdict(lambda: {"senses": 0, "missing": 0})
        for r in rows:
            key = key_fn(r) or "unknown"
            out[key]["senses"] += 1
            if is_blank(r["gloss_ne"]):
                out[key]["missing"] += 1
        return {k: v for k, v in sorted(out.items(), key=lambda kv: -kv[1]["missing"])}

    by_hsk = group(lambda r: hsk_band(r["hsk_level"]))
    by_freq = group(lambda r: freq_band(r["freq_rank"]))
    by_pos = group(lambda r: (r["pos_primary"] or "unknown"))
    by_domain = group(lambda r: (r["category"] or "unknown"))
    by_type = group(lambda r: entry_type(r))

    # ---- workload: unique glosses -----------------------------------------
    unique_gloss_all = {normalise_gloss(r["gloss_en"]) for r in missing if r["gloss_en"]}
    unique_atoms_all: set[str] = set()
    for r in missing:
        unique_atoms_all.update(atomic_glosses(r["gloss_en"]))

    def cohort_stats(limit: int) -> dict[str, object]:
        """Price the top-N entries by frequency rank (unknown rank last)."""
        ranked = sorted(
            (r for r in rows if r["freq_rank"] is not None),
            key=lambda r: (r["freq_rank"], r["sense_order"]),
        )
        kept: list[sqlite3.Row] = []
        seen_entries: set[int] = set()
        for r in ranked:
            if r["entry_id"] not in seen_entries:
                if len(seen_entries) >= limit:
                    break
                seen_entries.add(r["entry_id"])
            kept.append(r)
        missing_in = [r for r in kept if is_blank(r["gloss_ne"])]
        glosses = {normalise_gloss(r["gloss_en"]) for r in missing_in if r["gloss_en"]}
        atoms: set[str] = set()
        for r in missing_in:
            atoms.update(atomic_glosses(r["gloss_en"]))
        count = len(missing_in)
        return {
            "entries": len(seen_entries),
            "senses_missing": count,
            "unique_glosses": len(glosses),
            "unique_atomic_glosses": len(atoms),
            "hours_ai_at_0.47_per_s": round(count / SENSES_PER_SEC / 3600, 1),
            "cost_cheap_usd": round(count * COST_PER_SENSE_CHEAP, 2),
            "cost_frontier_usd": round(count * COST_PER_SENSE_FRONTIER, 2),
            "review_hours_at_300_per_hour": round(count / 300, 1),
        }

    cohorts = {f"top_{c}": cohort_stats(c) for c in args.top}

    # downstream queue: one row per unique (gloss, pos, category) so a gloss is
    # translated once and reused, as prompt N4 asks.
    queue_keys = Counter(
        (normalise_gloss(r["gloss_en"]), r["pos_primary"] or "", r["category"] or "")
        for r in missing if r["gloss_en"]
    )

    summary = {
        "database": str(db_path),
        "generated_from": "tools/audit_nepali.py (read-only)",
        "entries_total": len(all_entry_ids),
        "senses_total": total_senses,
        "senses_with_ne": len(have_ne),
        "senses_without_ne": len(missing),
        "senses_pct_with_ne": round(len(have_ne) / total_senses * 100, 2) if total_senses else 0.0,
        "entries_with_ne": len(entry_ids_with_ne),
        "entries_without_ne": len(all_entry_ids) - len(entry_ids_with_ne),
        "entries_pct_with_ne": round(len(entry_ids_with_ne) / len(all_entry_ids) * 100, 2) if all_entry_ids else 0.0,
        "existing_values_invalid": len(bad),
        "existing_values_invalid_by_reason": dict(Counter(reason for _, reason in bad)),
        "unique_glosses_missing": len(unique_gloss_all),
        "unique_atomic_glosses_missing": len(unique_atoms_all),
        "queue_items_by_gloss_pos_domain": len(queue_keys),
        "by_hsk": by_hsk,
        "by_freq_band": by_freq,
        "by_pos": by_pos,
        "by_domain": by_domain,
        "by_entry_type": by_type,
        "cohorts": cohorts,
        "model": {
            "senses_per_second": SENSES_PER_SEC,
            "cost_per_sense_cheap_usd": COST_PER_SENSE_CHEAP,
            "cost_per_sense_frontier_usd": COST_PER_SENSE_FRONTIER,
            "review_rate_per_hour": 300,
        },
    }

    # ---- CSVs --------------------------------------------------------------
    missing_csv = out_dir / "ne_audit_missing.csv"
    with missing_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "entry_id", "sense_id", "simplified", "pinyin", "gloss_en", "gloss_zh",
            "pos", "domain", "entry_type", "freq_rank", "hsk_level", "example_en",
        ])
        for r in sorted(missing, key=lambda r: (r["freq_rank"] or 10**9, r["sense_order"])):
            w.writerow([
                r["entry_id"], r["sense_id"], r["simplified"], r["pinyin_marked"],
                r["gloss_en"], (r["gloss_zh"] or ""), r["pos_primary"] or "",
                r["category"] or "", entry_type(r), r["freq_rank"] or "",
                r["hsk_level"] or "", examples.get(r["sense_id"], ""),
            ])

    bad_csv = out_dir / "ne_audit_bad_values.csv"
    with bad_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["entry_id", "sense_id", "simplified", "gloss_en", "gloss_ne", "ne_status", "reason"])
        for r, reason in bad:
            w.writerow([r["entry_id"], r["sense_id"], r["simplified"], r["gloss_en"],
                        r["gloss_ne"], r["ne_status"] or "", reason])

    (out_dir / "ne_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- human readable ----------------------------------------------------
    def table(title: str, data: dict[str, dict[str, int]]) -> list[str]:
        lines = [f"### {title}", "", "| group | senses | missing | coverage |", "|---|---:|---:|---:|"]
        for key, v in data.items():
            cov = 100 * (v["senses"] - v["missing"]) / v["senses"] if v["senses"] else 0
            lines.append(f"| {key} | {v['senses']:,} | {v['missing']:,} | {cov:.1f}% |")
        lines.append("")
        return lines

    md = [
        "# Nepali coverage audit (N2)", "",
        f"- database: `{db_path}`",
        f"- entries: **{summary['entries_total']:,}**, of which **{summary['entries_with_ne']:,}** "
        f"have at least one Nepali sense ({summary['entries_pct_with_ne']}%)",
        f"- senses: **{summary['senses_total']:,}**, of which **{summary['senses_with_ne']:,}** "
        f"have Nepali ({summary['senses_pct_with_ne']}%) and **{summary['senses_without_ne']:,}** do not",
        f"- existing Nepali values that fail a rule: **{summary['existing_values_invalid']:,}** "
        f"{summary['existing_values_invalid_by_reason']}",
        f"- unique English glosses still untranslated: **{summary['unique_glosses_missing']:,}** "
        f"({summary['unique_atomic_glosses_missing']:,} after splitting on `;` and `/`)",
        f"- queue items after grouping by gloss + POS + domain: "
        f"**{summary['queue_items_by_gloss_pos_domain']:,}**", "",
        "## Cost and time", "",
        "| cohort | entries | senses missing | unique glosses | AI hours @0.47/s | cheap ≈$ | frontier ≈$ | review hours @300/h |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, c in cohorts.items():
        md.append(f"| {name.replace('top_', 'top ')} | {c['entries']:,} | {c['senses_missing']:,} | "
                  f"{c['unique_glosses']:,} | {c['hours_ai_at_0.47_per_s']} | {c['cost_cheap_usd']:,} | "
                  f"{c['cost_frontier_usd']:,} | {c['review_hours_at_300_per_hour']} |")
    md += ["", "## Where the gap is", ""]
    md += table("By HSK level", by_hsk)
    md += table("By frequency band", by_freq)
    md += table("By part of speech", by_pos)
    md += table("By domain", by_domain)
    md += table("By entry type", by_type)
    (out_dir / "ne_audit_summary.md").write_text("\n".join(md), encoding="utf-8")

    print(json.dumps({k: summary[k] for k in (
        "entries_total", "senses_total", "senses_with_ne", "senses_without_ne",
        "entries_with_ne", "existing_values_invalid", "unique_glosses_missing",
        "unique_atomic_glosses_missing", "queue_items_by_gloss_pos_domain",
    )}, indent=2))
    print(f"\nwrote {missing_csv} ({missing_csv.stat().st_size/1e6:.1f} MB)")
    print(f"wrote {bad_csv}")
    print(f"wrote {out_dir / 'ne_audit_summary.json'}")
    print(f"wrote {out_dir / 'ne_audit_summary.md'}")
    for name, c in cohorts.items():
        print(f"{name}: {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
