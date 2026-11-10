import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "build" / "dictionary.sqlite"
con = sqlite3.connect(DB)
print("entry_images:", con.execute("SELECT COUNT(*) FROM entry_images").fetchone()[0])
print("distinct entries:", con.execute("SELECT COUNT(DISTINCT entry_id) FROM entry_images").fetchone()[0])
for pk in (72148, 72162):
    e = con.execute("SELECT simplified, traditional, category FROM entries WHERE entry_id=?", (pk,)).fetchone()
    s = con.execute("SELECT gloss_en FROM senses WHERE entry_id=? ORDER BY sense_order LIMIT 1", (pk,)).fetchone()
    i = con.execute("SELECT i.thumb_asset, ei.match_method FROM entry_images ei "
                    "JOIN images i ON i.image_id=ei.image_id WHERE ei.entry_id=?", (pk,)).fetchall()
    print(pk, e, s, i)
print("sibling rows:", con.execute(
    "SELECT entry_id, image_id, match_confidence FROM entry_images "
    "WHERE match_method='sibling'").fetchall())
