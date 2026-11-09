import sqlite3

DB = r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite"
con = sqlite3.connect(DB)
print("mountain entry 35110 senses:",
      con.execute("SELECT sense_id, gloss_en FROM senses WHERE entry_id=35110").fetchall())
print("examples for those senses:", con.execute(
    "SELECT e.example_id, e.en, e.review_status FROM examples e JOIN senses s "
    "ON s.sense_id=e.sense_id WHERE s.entry_id=35110").fetchall())
print("total examples:", con.execute("SELECT COUNT(*) FROM examples").fetchone()[0])
print("visible:", con.execute("SELECT COUNT(*) FROM examples WHERE review_status IN "
                             "('reviewed','imported')").fetchone()[0])
print("mountain 山 entry 88455? senses:", con.execute(
    "SELECT sense_id FROM senses WHERE entry_id=88455").fetchall())
