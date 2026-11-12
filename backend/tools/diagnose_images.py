"""Diagnose why a word shows no picture: coverage, asset columns, files on disk."""
import sqlite3
from pathlib import Path

REPO = Path(r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary")
DB = REPO / "backend" / "data" / "build" / "dictionary.sqlite"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

def q(sql):
    return con.execute(sql).fetchone()[0]

print("entries                ", q("SELECT COUNT(*) FROM entries"))
print("images total           ", q("SELECT COUNT(*) FROM images"))
print("images status approved ", q("SELECT COUNT(*) FROM images WHERE status='approved'"))
print("images asset_status approved", q("SELECT COUNT(*) FROM images WHERE COALESCE(asset_status,'')='approved'"))
print("images with thumb_asset", q("SELECT COUNT(*) FROM images WHERE thumb_asset IS NOT NULL AND thumb_asset<>''"))
print("images license_status verified", q("SELECT COUNT(*) FROM images WHERE COALESCE(license_status,'')='verified'"))
print("images license_status other", q("SELECT COUNT(*) FROM images WHERE COALESCE(license_status,'')<>'verified'"))
print()
print("entry_images rows      ", q("SELECT COUNT(*) FROM entry_images"))
print("distinct entries with an image", q("SELECT COUNT(DISTINCT entry_id) FROM entry_images"))
print("entries % coverage     ", round(100.0 * q("SELECT COUNT(DISTINCT entry_id) FROM entry_images") / q("SELECT COUNT(*) FROM entries"), 3))
print("entry_images whose image passes the app filter", q(
    "SELECT COUNT(*) FROM entry_images ei JOIN images i ON i.image_id=ei.image_id "
    "WHERE i.status='approved' AND COALESCE(i.asset_status,'')='approved' "
    "AND i.thumb_asset IS NOT NULL AND i.thumb_asset<>''"))
print()
print("concepts               ", q("SELECT COUNT(*) FROM concepts"))
print("concept_images         ", q("SELECT COUNT(*) FROM concept_images"))
print("entry_concepts         ", q("SELECT COUNT(*) FROM entry_concepts"))
print("concept_lookup_cache   ", q("SELECT COUNT(*) FROM concept_lookup_cache"))
print()
print("sample entry_images:")
for row in con.execute("SELECT ei.entry_id, e.simplified, ei.image_id, ei.rank, "
                       "ei.match_method, COALESCE(ei.match_confidence, ei.confidence) "
                       "FROM entry_images ei JOIN entries e ON e.entry_id=ei.entry_id LIMIT 5"):
    print("  ", row)
print()
print("sample images rows (thumb_asset / status / asset_status):")
for row in con.execute("SELECT image_id, substr(title,1,28), thumb_asset, status, asset_status, "
                       "license_status FROM images ORDER BY image_id LIMIT 6"):
    print("  ", row)
print()
print("thumb_asset prefixes:")
from collections import Counter
c = Counter()
for (val,) in con.execute("SELECT thumb_asset FROM images WHERE thumb_asset IS NOT NULL AND thumb_asset<>''"):
    c["/".join(val.split("/")[:2])] += 1
print("  ", c.most_common(5))
print()
print("images missing thumb_asset:")
for row in con.execute("SELECT image_id, substr(title,1,30), thumb_path ->", ) if False else []:
    pass
for row in con.execute("SELECT image_id, substr(title,1,34), thumb_path FROM images "
                       "WHERE thumb_asset IS NULL OR thumb_asset=''"):
    print("  ", row)

assets = REPO / "assets" / "images"
webp = list(assets.rglob("*.webp")) + list(assets.rglob("*.jpg")) + list(assets.rglob("*.png"))
print()
print("asset files under assets/images:", len(webp))
print("top-level dirs:", sorted({p.parent.name for p in webp})[:10])
con.close()
