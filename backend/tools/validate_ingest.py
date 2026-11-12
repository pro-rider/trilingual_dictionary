"""Post-ingestion validation: prove entries/senses untouched and the staging table is sane."""
import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite")
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

print("entries", con.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
print("senses ", con.execute("SELECT COUNT(*) FROM senses").fetchone()[0])
print("examples", con.execute("SELECT COUNT(*) FROM examples").fetchone()[0])
print()
print("staging by status:")
for status, count in con.execute(
        "SELECT status, COUNT(*) FROM words3000_candidates GROUP BY status ORDER BY 2 DESC"):
    print(f"  {status:18} {count:,}")
print()
print("staging by source:")
for source, count in con.execute(
        "SELECT source, COUNT(*) FROM words3000_candidates GROUP BY source ORDER BY 2 DESC"):
    print(f"  {source:24} {count:,}")
print()
print("rows with empty pinyin:",
      con.execute("SELECT COUNT(*) FROM words3000_candidates WHERE pinyin IS NULL OR pinyin=''").fetchone()[0])
print("rows with gloss_en:", con.execute(
    "SELECT COUNT(*) FROM words3000_candidates WHERE gloss_en IS NOT NULL AND gloss_en<>''").fetchone()[0])
print("rows with gloss_zh:", con.execute(
    "SELECT COUNT(*) FROM words3000_candidates WHERE gloss_zh IS NOT NULL AND gloss_zh<>''").fetchone()[0])
print("rows with gloss_ne:", con.execute(
    "SELECT COUNT(*) FROM words3000_candidates WHERE gloss_ne IS NOT NULL AND gloss_ne<>''").fetchone()[0])
print("rows whose gloss_ne has Latin letters (suspect):", con.execute(
    "SELECT COUNT(*) FROM words3000_candidates WHERE gloss_ne GLOB '*[A-Za-z]*'").fetchone()[0])
print("rows containing U+FFFD:",
      con.execute("SELECT COUNT(*) FROM words3000_candidates WHERE word LIKE '%\ufffd%' OR gloss_zh LIKE '%\ufffd%'").fetchone()[0])
print()
print("new rows whose word already exists in entries (should be 0):", con.execute(
    "SELECT COUNT(*) FROM words3000_candidates w WHERE w.source='user-raw-2026-11-12' "
    "AND w.word IN (SELECT simplified FROM entries)"
    " AND w.word NOT IN (SELECT word FROM words3000_candidates WHERE source<>'user-raw-2026-11-12' )"
).fetchone()[0])
print("char_count mismatches:", con.execute(
    "SELECT COUNT(*) FROM words3000_candidates WHERE char_count <> LENGTH(word)").fetchone()[0])
print()
print("longest headwords:")
for word, count in con.execute(
        "SELECT word, LENGTH(word) FROM words3000_candidates ORDER BY LENGTH(word) DESC LIMIT 5"):
    print(f"  {word} ({count})")
con.close()
