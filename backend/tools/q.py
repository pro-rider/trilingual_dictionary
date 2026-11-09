import sqlite3

DB = r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite"
con = sqlite3.connect(DB)
words = ["玩具", "声音", "山", "水", "书", "老师", "电脑", "狗", "猫", "飞机", "手机", "火车",
         "森林", "苹果", "学校", "医院"]
print("images:", con.execute("SELECT COUNT(*) FROM images").fetchone()[0])
print("entry_images:", con.execute("SELECT COUNT(*) FROM entry_images").fetchone()[0],
      "| distinct entries:",
      con.execute("SELECT COUNT(DISTINCT entry_id) FROM entry_images").fetchone()[0])
print()
print(f"{'word':<6} {'method':<10} {'conf':<5} {'status':<9} {'licence':<14} thumb")
for w in words:
    row = con.execute(
        "SELECT ei.match_method, ei.match_confidence, i.status, i.license, "
        "       i.thumb_asset, i.thumb_bytes "
        "FROM entries e JOIN entry_images ei ON ei.entry_id=e.entry_id "
        "JOIN images i ON i.image_id=ei.image_id "
        "WHERE e.simplified=? LIMIT 1", (w,)).fetchone()
    if row:
        print(f"{w:<6} {row[0] or '':<10} {row[1] or '':<5} {row[2] or '':<9} "
              f"{(row[3] or '')[:14]:<14} {row[5]}B  {row[4]}")
    else:
        print(f"{w:<6} {'-':<10} {'-':<5} {'MISSING':<9}")
print()
print("status distribution:",
      con.execute("SELECT status, COUNT(*) FROM images GROUP BY status").fetchall())
print("licences:",
      con.execute("SELECT license, COUNT(*) FROM images GROUP BY license").fetchall())
