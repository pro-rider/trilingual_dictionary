import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "build" / "dictionary.sqlite"
c = sqlite3.connect(DB)
words = ["山", "玩具", "声音", "苹果", "猫", "鱼", "森林", "老师", "悲伤", "桌子", "汽车", "书", "水", "瑜伽垫", "贸易", "行为"]
rows = c.execute(
    "select e.simplified, i.title, i.license, i.thumb_bytes, i.asset_status "
    "from entry_images ei join entries e on e.entry_id = ei.entry_id "
    "join images i on i.image_id = ei.image_id").fetchall()
print("mappings:", len(rows))
for r in rows:
    if r[0] in words:
        print(r)
print("images:", c.execute("select count(*) from images").fetchone()[0])
print("approved:", c.execute("select count(*) from images where asset_status='approved'").fetchone()[0])
