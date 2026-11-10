import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "build" / "dictionary.sqlite"
con = sqlite3.connect(DB)
print("quarantined rows:", con.execute(
    "SELECT example_id, sense_id, en, quarantine_reason FROM examples "
    "WHERE review_status='quarantined'").fetchall())
print("owner words:", con.execute(
    "SELECT e.simplified, en, s.sense_id FROM examples ex JOIN senses s "
    "ON s.sense_id = ex.sense_id JOIN entries e ON e.entry_id = s.entry_id "
    "WHERE ex.review_status='quarantined'").fetchall())
print("visible examples for 山 entries:", con.execute(
    "SELECT e.simplified, COUNT(*) FROM examples ex JOIN senses s "
    "ON s.sense_id=ex.sense_id JOIN entries e ON e.entry_id=s.entry_id "
    "WHERE e.simplified='山' AND ex.review_status IN ('reviewed','imported') "
    "GROUP BY e.simplified").fetchall())
