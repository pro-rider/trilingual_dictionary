import sqlite3

DB = r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite"
con = sqlite3.connect(DB)
words = ["玩具", "声音", "书", "老师", "狗", "猫", "火车", "学校", "医院"]
for w in words:
    e = con.execute("SELECT entry_id, simplified, category, freq_rank FROM entries "
                    "WHERE simplified=?", (w,)).fetchone()
    if not e:
        print(f"{w}: NO ENTRY")
        continue
    ec = con.execute("SELECT COUNT(*) FROM entry_concepts WHERE entry_id=?", (e[0, ] if False else e[0],)).fetchone()[0]
    print(f"{w}: entry_id={e[0]} category={e[2]} freq={e[3]} entry_concepts={ec}")
print()
for w in ["玩具", "声音", "书"]:
    rows = con.execute(
        "SELECT ec.concept_id, c.qid, c.label_zh, c.category FROM entry_concepts ec "
        "JOIN concepts c ON c.concept_id=ec.concept_id JOIN entries e ON e.entry_id=ec.entry_id "
        "WHERE e.simplified=?", (w,)).fetchall()
    print(w, rows)
