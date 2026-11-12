import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite")
con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
print([r[1] for r in con.execute("pragma table_info(senses)")])
print(con.execute("select * from sources").fetchall())
print([r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")])
print("sample senses for a multi-sense entry 76087:", con.execute("select sense_id, sense_order, gloss_en, gloss_zh from senses where entry_id=76087").fetchall())
print("sample single", con.execute("select sense_id, entry_id, sense_order, gloss_en from senses limit 3").fetchall())
print("def sample 16-40:", con.execute("select entry_id,title,definition_zh from gloss_zh_wikt_candidates where def_chars between 16 and 40 limit 5").fetchall())
print("refs stubs:", con.execute("select count(*) from gloss_zh_wikt_candidates where definition_zh like '见%' or definition_zh like '参见%' or definition_zh like '另见%' or definition_zh like '同%'").fetchone())
