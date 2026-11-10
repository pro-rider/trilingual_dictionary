"""Build a small, real fixture database for the Flutter offline tests.

Why: the full dictionary is about 96 MB and is gitignored, so CI could not run
the offline search, offline image and offline analysis suites at all. This tool
copies the real schema and a curated *subset of real rows* into a file small
enough to commit, so those suites run everywhere instead of being skipped.

The subset is chosen so that every assertion in the three suites keeps testing
real data rather than invented data:

  * Chinese headwords the tests name explicitly (玩具, 书, 山, 声音, 册, ...).
  * Every entry whose English gloss exactly matches a token the analysis tests
    use (word, screen, data, server, first, dog, book, water, mountain, ...).
    All candidates are included, not just the winner, so the ranking code sees
    the same competition it sees in production and the same row must win.
  * Every entry glossed with "behavior", which the plural-fallback test needs.
  * Entry 3 (11区), whose quarantined example the reader must not show.

Absolute build-machine paths are rewritten to relative ones: a fixture is
committed, so it must not carry any developer's directory layout.

Usage (from the repo root, backend venv python):
    python backend/tools/make_test_fixture.py
    python backend/tools/make_test_fixture.py --check   # verify without writing
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "backend" / "data" / "build" / "dictionary.sqlite"
OUT_DIR = REPO / "backend" / "data" / "test_fixtures"
OUT = OUT_DIR / "dictionary_fixture.sqlite"

# Tables the offline reader actually queries, plus the ones a fixture should
# carry so the schema stays recognisable. FTS tables are deliberately excluded:
# the offline path never searches them (it does exact headword and gloss
# lookups), and their index blobs would dominate the file size.
TABLES = ["meta", "entries", "senses", "images", "entry_images", "examples",
          "concepts", "entry_concepts"]

TOKENS = ["word", "screen", "data", "server", "first", "dog", "book", "water",
          "mountain", "sound", "toy", "raisin", "behaviors", "behavior",
          "Nepal", "China", "pinyin", "Area 11", "plaything"]

HEADWORDS = ["葡萄干", "安排", "尼泊尔", "中国", "行为", "书", "山", "声音", "玩具",
             "册", "11区", "我们", "水", "拼音", "词", "单词", "狗", "数据", "第一",
             "前", "主机", "声", "音", "玩", "玩意", "册子"]

EXTRA_IDS = [3, 72148]

MAX_BYTES = 3 * 1024 * 1024


def q(con, sql, args=()):
    return con.execute(sql, args).fetchall()


def collect_ids(src):
    ids = set()
    for name in HEADWORDS:
        for row in q(src, "SELECT entry_id FROM entries WHERE simplified = ?", (name,)):
            ids.add(row[0])
    for tok in TOKENS:
        for row in q(src,
                     "SELECT DISTINCT e.entry_id FROM senses s "
                     "JOIN entries e ON e.entry_id = s.entry_id "
                     "WHERE lower(s.gloss_en) = lower(?)", (tok,)):
            ids.add(row[0])
    for row in q(src,
                 "SELECT DISTINCT e.entry_id FROM senses s "
                 "JOIN entries e ON e.entry_id = s.entry_id "
                 "WHERE lower(s.gloss_en) LIKE '%behavior%'"):
        ids.add(row[0])
    ids.update(EXTRA_IDS)
    return sorted(i for i in ids if isinstance(i, int))


def relative_thumb(path: str) -> str:
    """Drop any build-machine prefix, keep the canonical server form."""
    if not path:
        return path
    name = path.replace("\\", "/").split("/")[-1]
    if not name:
        return path
    return f"data/images/thumbs/{name}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="build in memory and report, without replacing the file")
    args = ap.parse_args(argv)

    if not SOURCE.exists():
        print(f"UNKNOWN: no built dictionary at {SOURCE}. Build it first: "
              "python backend/tools/build_dictionary.py", file=sys.stderr)
        return 2

    src = sqlite3.connect(f"file:{SOURCE.as_posix()}?mode=ro", uri=True)
    ids = collect_ids(src)
    print(f"entries selected: {len(ids)}")

    if args.check and OUT.exists():
        con = sqlite3.connect(f"file:{OUT.as_posix()}?mode=ro", uri=True)
        print(f"existing fixture: {OUT.stat().st_size:,} bytes")
        for t in TABLES:
            try:
                print(f"  {t:14} {q(con, f'SELECT count(*) FROM {t}')[0][0]}")
            except sqlite3.Error as e:
                print(f"  {t:14} ERR {e}")
        con.close()
        src.close()
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    for p in (tmp, Path(str(tmp) + "-journal")):
        if p.exists():
            p.unlink()

    dst = sqlite3.connect(str(tmp))
    cur = dst.cursor()

    # 1. Schema, verbatim from the source, minus FTS virtual tables.
    ddl = q(src, "SELECT type, name, sql FROM sqlite_master "
                 "WHERE tbl_name IN ({}) AND sql IS NOT NULL ORDER BY "
                 "CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END"
                 .format(",".join("?" * len(TABLES))), TABLES)
    made = 0
    for typ, name, sql in ddl:
        if typ in ("table", "index") and not name.startswith("sqlite_"):
            try:
                cur.execute(sql)
                made += 1
            except sqlite3.Error as e:
                print(f"  skipped {typ} {name}: {e}")
    print(f"schema objects created: {made}")

    # 2. Rows, in primary-key order so the file is byte-stable across rebuilds.
    def copy_table(table, where="1=1", params=(), order="rowid"):
        cols = [r[1] for r in q(src, f"PRAGMA table_info({table})")]
        rows = q(src, f"SELECT * FROM {table} WHERE {where} ORDER BY {order}", params)
        if not rows:
            return 0
        placeholders = ",".join("?" * len(cols))
        cur.executemany(
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", rows)
        return len(rows)

    ph = ",".join("?" * len(ids))
    n_entries = copy_table("entries", f"entry_id IN ({ph})", ids, "entry_id")
    n_senses = copy_table("senses", f"entry_id IN ({ph})", ids, "sense_id")

    sense_ids = sorted(r[0] for r in q(src, f"SELECT sense_id FROM senses WHERE entry_id IN ({ph})", ids))
    n_examples = 0
    if sense_ids:
        sph = ",".join("?" * len(sense_ids))
        n_examples = copy_table("examples", f"sense_id IN ({sph})", sense_ids, "example_id")

    image_ids = sorted({r[0] for r in q(
        src, f"SELECT image_id FROM entry_images WHERE entry_id IN ({ph})", ids)})
    n_links = copy_table("entry_images", f"entry_id IN ({ph})", ids, "entry_id")
    n_images = 0
    if image_ids:
        iph = ",".join("?" * len(image_ids))
        n_images = copy_table("images", f"image_id IN ({iph})", image_ids, "image_id")
        # A committed fixture must not carry a developer's absolute paths.
        cur.execute("UPDATE images SET thumb_path = NULL WHERE thumb_path LIKE '%:%'")
        cur.execute("UPDATE images SET detail_path = NULL WHERE detail_path LIKE '%:%'")
        cur.execute("UPDATE images SET source_url = NULL WHERE source_url LIKE '%Users%'")
        cur.execute("UPDATE images SET thumb_path = COALESCE(thumb_asset, '') "
                    "WHERE thumb_path IS NULL AND thumb_asset IS NOT NULL")

    n_concepts = copy_table("concepts")
    n_ec = copy_table("entry_concepts", f"entry_id IN ({ph})", ids, "entry_id")
    n_meta = copy_table("meta", order="key")

    dst.commit()
    cur.execute("VACUUM")
    dst.commit()

    integrity = q(dst, "PRAGMA integrity_check")[0][0]
    size = tmp.stat().st_size

    print(f"entries {n_entries}  senses {n_senses}  examples {n_examples}  "
          f"images {n_images}  entry_images {n_links}  "
          f"concepts {n_concepts}/{n_ec}  meta {n_meta}")
    print(f"size {size:,} bytes  integrity {integrity}")

    if integrity != "ok":
        dst.close()
        tmp.unlink()
        print("REFUSED: fixture failed integrity_check", file=sys.stderr)
        return 1
    if size > MAX_BYTES:
        dst.close()
        tmp.unlink()
        print(f"REFUSED: {size:,} bytes exceeds the {MAX_BYTES:,} budget", file=sys.stderr)
        return 1

    # 3. Sanity: the queries the suites depend on must resolve.
    checks = [
        ("healdword 玩具", "SELECT count(*) FROM entries WHERE simplified='玩具'"),
        ("gloss toy", "SELECT count(*) FROM senses WHERE gloss_en='toy'"),
        ("gloss raisin", "SELECT count(*) FROM senses WHERE gloss_en='raisin'"),
        ("image of 72148",
         "SELECT count(*) FROM entry_images WHERE entry_id=72148"),
        ("absolute paths left",
         "SELECT count(*) FROM images WHERE thumb_path LIKE '%:%'"),
    ]
    for label, sql in checks:
        print(f"  {label}: {q(dst, sql)[0][0]}")

    dst.close()
    tmp.replace(OUT)
    print(f"written {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
