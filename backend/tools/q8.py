import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "build" / "dictionary.sqlite"
con = sqlite3.connect(DB)
print("entry_images", con.execute("SELECT COUNT(*) FROM entry_images").fetchone()[0])
print("distinct", con.execute("SELECT COUNT(DISTINCT entry_id) FROM entry_images").fetchone()[0])
print("72162:", con.execute(
    "SELECT i.thumb_asset, ei.match_method FROM entry_images ei JOIN images i "
    "ON i.image_id=ei.image_id WHERE ei.entry_id=72162").fetchall())
print("concept of 72148:", con.execute(
    "SELECT c.concept_id, c.label_en, c.label_zh FROM entry_concepts ec "
    "JOIN concepts c ON c.concept_id=ec.concept_id WHERE ec.entry_id=72148").fetchall())
print("entries with gloss 'toy' and no image:", con.execute(
    "SELECT e.entry_id, e.simplified, e.category FROM entries e "
    "WHERE (SELECT s.gloss_en FROM senses s WHERE s.entry_id=e.entry_id "
    "ORDER BY s.sense_order LIMIT 1)='toy' "
    "AND e.entry_id NOT IN (SELECT entry_id FROM entry_images) LIMIT 10").fetchall())
