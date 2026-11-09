import sqlite3

DB = r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite"
con = sqlite3.connect(DB)
for w in ("光", "书", "声音", "玩具", "山", "水", "老师", "狗"):
    rows = con.execute(
        "SELECT e.entry_id, i.thumb_asset FROM entry_images ei JOIN images i "
        "ON i.image_id=ei.image_id JOIN entries e ON e.entry_id=ei.entry_id "
        "WHERE e.simplified = ? AND i.status='approved' LIMIT 3", (w,)).fetchall()
    print(w, rows)
