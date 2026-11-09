import sqlite3
import os

path = os.path.expandvars(r"%TEMP%\dev.sqlite")
con = sqlite3.connect(path)
print("images", con.execute("SELECT COUNT(*) FROM images").fetchone()[0])
print("entry_images", con.execute("SELECT COUNT(*) FROM entry_images").fetchone()[0])
print("meta", con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchall())
row = con.execute(
    "SELECT i.image_id, i.status, i.asset_status, i.thumb_asset "
    "FROM entry_images ei JOIN images i ON i.image_id=ei.image_id "
    "WHERE ei.entry_id=72148").fetchall()
print("toy row", row)
print("entry 72148 simplified:",
      con.execute("SELECT simplified FROM entries WHERE entry_id=72148").fetchall())
