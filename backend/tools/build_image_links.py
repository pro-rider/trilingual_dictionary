"""Phase 1 — make one approved picture reach its whole concept family.

The library holds 77 approved photographs; almost every word has none. Most of
them are attached to a *concept*, but the client reads `entry_images`, and only
the one entry that happened to be crawled ever got a row. 书 has a photograph and
书籍 does not; 城市 and 都会 share concept wd:Q515 and only one of them was linked.

This tool redistributes the existing assets, nothing else:

  * direct rows (wikidata-p18, zh-title, en-gloss, sibling, …) are left untouched
    and always win;
  * an entry that belongs to a concept with a usable picture inherits it at
    confidence 0.65, rank 2;
  * an entry whose headword equals a concept's Chinese label inherits at 0.75,
    because that is an exact name match rather than a family hop;
  * nothing is inherited when the concept's only picture fails the client's own
    filter (approved + asset approved + thumbnail present).

Idempotent: every inherited row is tagged `concept-inherit` / `concept-label` and
rebuilt from scratch on each run, so a second run adds zero rows.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "build" / "dictionary.sqlite"

USABLE_IMAGE = (
    "i.status = 'approved' "
    "AND COALESCE(i.asset_status, '') = 'approved' "
    "AND i.thumb_asset IS NOT NULL AND i.thumb_asset <> ''"
)

INHERIT = "concept-inherit"
LABEL = "concept-label"


def coverage(con: sqlite3.Connection) -> int:
    return con.execute(
        "SELECT COUNT(DISTINCT entry_id) FROM entry_images").fetchone()[0]


def best_image_per_concept(con: sqlite3.Connection) -> dict[str, tuple[int, float, str]]:
    rows = con.execute(
        f"SELECT ci.concept_id, ci.image_id, ci.relevance, ci.is_primary, i.title "
        f"FROM concept_images ci JOIN images i ON i.image_id = ci.image_id "
        f"WHERE {USABLE_IMAGE} "
        f"ORDER BY ci.concept_id, ci.is_primary DESC, ci.relevance DESC, i.image_id"
    ).fetchall()
    best: dict[str, tuple[int, float, str]] = {}
    for concept_id, image_id, relevance, _primary, title in rows:
        best.setdefault(concept_id, (image_id, float(relevance or 0), title or ""))
    return best


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    before = coverage(con)
    direct_rows = con.execute(
        "SELECT COUNT(*) FROM entry_images WHERE match_method NOT IN (?,?)",
        (INHERIT, LABEL)).fetchone()[0]
    print(f"entries with a picture before: {before:,}")
    print(f"direct rows kept: {direct_rows:,}")

    best = best_image_per_concept(con)
    print(f"concepts holding at least one usable picture: {len(best):,}")

    direct_entries = {r[0] for r in con.execute(
        "SELECT entry_id FROM entry_images WHERE match_method NOT IN (?,?)",
        (INHERIT, LABEL))}

    # 1. family inheritance through entry_concepts
    family: dict[int, tuple[str, int, float, str]] = {}
    for row in con.execute(
        "SELECT ec.entry_id, ec.concept_id, ec.confidence, e.simplified "
        "FROM entry_concepts ec JOIN entries e ON e.entry_id = ec.entry_id"
    ):
        if row["entry_id"] in direct_entries:
            continue
        picked = best.get(row["concept_id"])
        if not picked:
            continue
        image_id, relevance, title = picked
        # entry_concepts.confidence is how sure the concept match was; the
        # inheritance confidence is that, capped, because the picture is one
        # hop further away from the word than the concept is.
        conf = round(min(0.65, 0.65 * float(row["confidence"] or 0.8) / 0.9), 2)
        prev = family.get(row["entry_id"])
        if prev is None or conf > prev[2]:
            family[row["entry_id"]] = (row["concept_id"], image_id, conf, title)

    # 2. exact Chinese-label inheritance (concept label == headword)
    label_rows: dict[int, tuple[str, int, float, str]] = {}
    for row in con.execute(
        "SELECT e.entry_id, c.concept_id, LENGTH(e.simplified) AS n, e.simplified "
        "FROM entries e JOIN concepts c ON c.label_zh = e.simplified"
    ):
        if row["entry_id"] in direct_entries or row["entry_id"] in family:
            continue
        picked = best.get(row["concept_id"])
        if not picked:
            continue
        image_id, relevance, title = picked
        prev = label_rows.get(row["entry_id"])
        if prev is None:
            label_rows[row["entry_id"]] = (row["concept_id"], image_id, 0.75, title)

    print(f"family inheritance candidates: {len(family):,}")
    print(f"exact-label inheritance candidates: {len(label_rows):,}")

    if args.dry_run:
        for entry_id, (concept_id, image_id, conf, title) in list(family.items())[:5]:
            print(f"  [dry] entry {entry_id} <- {concept_id} image {image_id} "
                  f"({conf}) {title[:40]}")
        for entry_id, (concept_id, image_id, conf, title) in list(label_rows.items())[:5]:
            print(f"  [dry] entry {entry_id} <- label {concept_id} image {image_id} "
                  f"({conf}) {title[:40]}")
        after = len(direct_entries) + len(family) + len(label_rows)
        print(f"\ncoverage {before:,} -> {after:,}  (+{after - before:,})  "
              f"({100.0 * after / con.execute('SELECT COUNT(*) FROM entries').fetchone()[0]:.3f}%)")
        print("dry run: nothing written")
        return 0

    con.execute("DELETE FROM entry_images WHERE match_method IN (?,?)", (INHERIT, LABEL))
    for entry_id, (concept_id, image_id, conf, title) in family.items():
        con.execute(
            "INSERT OR IGNORE INTO entry_images(entry_id, sense_id, image_id, "
            "confidence, rank, match_method, concept_id, match_confidence, "
            "match_reason, device_hint) VALUES (?,NULL,?,?,2,?,?,?,?,?)",
            (entry_id, image_id, conf, INHERIT, concept_id, conf,
             f"same concept {concept_id} as a word that already had a picture",
             "not_cached"))
    for entry_id, (concept_id, image_id, conf, title) in label_rows.items():
        con.execute(
            "INSERT OR IGNORE INTO entry_images(entry_id, sense_id, image_id, "
            "confidence, rank, match_method, concept_id, match_confidence, "
            "match_reason, device_hint) VALUES (?,NULL,?,?,2,?,?,?,?,?)",
            (entry_id, image_id, conf, LABEL, concept_id, conf,
             f"headword equals the concept label of {concept_id}",
             "not_cached"))
    con.commit()

    after = coverage(con)
    total_entries = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    print(f"\ncoverage {before:,} -> {after:,} entries "
          f"(+{after - before:,}, {100.0 * before / total_entries:.3f}% -> "
          f"{100.0 * after / total_entries:.3f}%)")
    print("rows by method:")
    for row in con.execute("SELECT match_method, COUNT(*) FROM entry_images "
                           "GROUP BY match_method ORDER BY 2 DESC"):
        print(f"  {row[0]:24} {row[1]:>6}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
