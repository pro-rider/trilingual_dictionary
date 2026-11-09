import sqlite3

DB = r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite"
con = sqlite3.connect(DB)


def look(word):
    rows = con.execute(
        "SELECT e.entry_id, e.simplified, e.category, "
        "(SELECT s.gloss_en FROM senses s WHERE s.entry_id=e.entry_id "
        " ORDER BY s.sense_order LIMIT 1) g, "
        "(SELECT COUNT(*) FROM entry_images ei WHERE ei.entry_id=e.entry_id) imgs "
        "FROM entries e WHERE "
        "EXISTS (SELECT 1 FROM senses s2 WHERE s2.entry_id=e.entry_id "
        "        AND s2.gloss_en = ?) "
        "OR e.simplified = ? LIMIT 8", (word, word)).fetchall()
    print(word, "->")
    for r in rows:
        print("   ", r)


for w in ("book", "sound", "toy", "water", "school", "hospital", "dog", "cat", "teacher"):
    look(w)
