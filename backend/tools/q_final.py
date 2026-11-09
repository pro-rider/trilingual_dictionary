import sqlite3

DB = r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite"
con = sqlite3.connect(DB)
print("images", con.execute("SELECT COUNT(*) FROM images").fetchone()[0])
print("entry_images", con.execute("SELECT COUNT(*) FROM entry_images").fetchone()[0])
print("distinct entries", con.execute("SELECT COUNT(DISTINCT entry_id) FROM entry_images").fetchone()[0])
print("by method", con.execute(
    "SELECT match_method, COUNT(*) FROM entry_images GROUP BY 1").fetchall())
print("servable", con.execute(
    "SELECT COUNT(*) FROM images WHERE status='approved' AND "
    "COALESCE(asset_status,'approved')='approved'").fetchone()[0])
print("thumb bytes", con.execute("SELECT SUM(thumb_bytes) FROM images").fetchone()[0])
print("examples", con.execute(
    "SELECT review_status, COUNT(*) FROM examples GROUP BY 1").fetchall())
print("examples words", con.execute(
    "SELECT COUNT(DISTINCT s.entry_id) FROM examples ex JOIN senses s ON s.sense_id=ex.sense_id "
    "WHERE ex.review_status IN ('reviewed','imported')").fetchone()[0])
