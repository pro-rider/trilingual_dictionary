import os
import sqlite3

con = sqlite3.connect(os.path.expandvars(r"%TEMP%\dev.sqlite"))
print("tables:", [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")])
print()
print("mountain-like examples:", con.execute(
    "SELECT ex.example_id, ex.review_status, ex.en FROM examples ex "
    "WHERE ex.en LIKE '%mountain%' LIMIT 5").fetchall())
print()
print("山路 entry 35110 image:", con.execute(
    "SELECT i.thumb_asset, ei.match_method FROM entry_images ei JOIN images i "
    "ON i.image_id=ei.image_id WHERE ei.entry_id=35110").fetchall())
print("entry_images:", con.execute("SELECT COUNT(*) FROM entry_images").fetchone()[0])
