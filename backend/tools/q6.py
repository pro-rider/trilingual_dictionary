import os
import sqlite3

con = sqlite3.connect(os.path.expandvars(r"%TEMP%\dev.sqlite"))
row = con.execute(
    "SELECT typeof(i.image_id), typeof(i.width), typeof(i.height), "
    "       i.width, i.height, typeof(COALESCE(ei.match_confidence, ei.confidence)), "
    "       typeof(ei.rank) "
    "FROM entry_images ei JOIN images i ON i.image_id=ei.image_id "
    "WHERE ei.entry_id=72148").fetchall()
print("types:", row)
cols = con.execute("PRAGMA table_info(images)").fetchall()
print("schema:", [(c[1], c[2]) for c in cols])
