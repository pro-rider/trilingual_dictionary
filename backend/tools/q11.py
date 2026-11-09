import sqlite3

DB = r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite"
con = sqlite3.connect(DB)
print("row:", con.execute(
    "SELECT ex.example_id, ex.sense_id, ex.review_status, s.entry_id, e.simplified "
    "FROM examples ex JOIN senses s ON s.sense_id=ex.sense_id "
    "JOIN entries e ON e.entry_id=s.entry_id WHERE ex.en LIKE '%climbed the mountain%'"
).fetchall())
print("examples count by status:", con.execute(
    "SELECT review_status, COUNT(*) FROM examples GROUP BY review_status").fetchall())
print("entries with visible examples:", con.execute(
    "SELECT COUNT(DISTINCT s.entry_id) FROM examples ex JOIN senses s "
    "ON s.sense_id=ex.sense_id WHERE ex.review_status IN ('reviewed','imported')").fetchone()[0])
