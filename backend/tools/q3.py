import sqlite3
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary")
DB = ROOT / "backend" / "data" / "build" / "dictionary.sqlite"
con = sqlite3.connect(DB)
rows = con.execute(
    "SELECT i.image_id, i.thumb_asset, i.thumb_bytes, COALESCE(i.asset_status,'') "
    "FROM images i").fetchall()
ok = bad = missing = 0
for image_id, rel, nbytes, st in rows:
    p = ROOT / (rel or "")
    if not rel:
        bad += 1
    elif p.exists() and p.parent.name == "thumbs":
        ok += 1
    else:
        bad += 1
print(f"assets={len(rows)} flat_and_present={ok} bad_path={bad}")
print("asset_status:", con.execute(
    "SELECT COALESCE(asset_status,'(null)'), COUNT(*) FROM images GROUP BY 1").fetchall())
print("servable (approved + asset ok):", con.execute(
    "SELECT COUNT(*) FROM images WHERE status='approved' AND "
    "COALESCE(asset_status,'approved') IN ('approved','')").fetchone()[0])
total = con.execute("SELECT COALESCE(SUM(thumb_bytes),0) FROM images").fetchone()[0]
print(f"thumbnail bytes total={total} avg={total // max(len(rows),1)}")
print("distinct entries served:", con.execute(
    "SELECT COUNT(DISTINCT ei.entry_id) FROM entry_images ei JOIN images i "
    "ON i.image_id=ei.image_id WHERE i.status='approved'").fetchone()[0])
