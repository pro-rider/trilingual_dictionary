import sqlite3

DB = r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite"
con = sqlite3.connect(DB)
row = con.execute(
    "SELECT ei.entry_id, ei.image_id, i.status, i.asset_status, i.thumb_asset, "
    "       i.thumb_bytes, ei.rank, i.detail_url, i.license "
    "FROM entry_images ei JOIN images i ON i.image_id=ei.image_id "
    "WHERE ei.entry_id=72148").fetchall()
print("toy rows:", row)
print()
print("app query result:", con.execute(
    "SELECT i.image_id, i.thumb_asset FROM entry_images ei JOIN images i "
    "ON i.image_id=ei.image_id WHERE ei.entry_id=72148 AND i.status='approved' "
    "AND COALESCE(i.asset_status,'approved')='approved' "
    "AND i.thumb_asset IS NOT NULL AND i.thumb_asset!='' ORDER BY ei.rank LIMIT 1"
).fetchall())
print()
print("meta schema_version:", con.execute(
    "SELECT value FROM meta WHERE key='schema_version'").fetchall())
print("images count in this file:", con.execute("SELECT COUNT(*) FROM images").fetchone()[0])
