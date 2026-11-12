import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite")
con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

print("total", con.execute("select count(*) from gloss_zh_wikt_candidates").fetchone()[0])
print("by pos", con.execute("select pos, count(*) from gloss_zh_wikt_candidates group by pos order by 2 desc limit 12").fetchall())
print("def_chars buckets", con.execute("""
select case when def_chars=0 then '0' when def_chars<=5 then '1-5' when def_chars<=15 then '6-15'
when def_chars<=40 then '16-40' when def_chars<=100 then '41-100' else '100+' end b, count(*)
from gloss_zh_wikt_candidates group by b order by b""").fetchall())
print("with examples", con.execute("select count(*) from gloss_zh_wikt_candidates where example_count>0").fetchone()[0])
print("template junk", con.execute("select count(*) from gloss_zh_wikt_candidates where definition_zh like '%{{%' or definition_zh like '%|%'").fetchone()[0])
print("empty def", con.execute("select count(*) from gloss_zh_wikt_candidates where definition_zh is null or trim(definition_zh)=''").fetchone()[0])
print("license", con.execute("select license, source, count(*) from gloss_zh_wikt_candidates group by license, source").fetchall())

# join quality against entries
q = """
select
 sum(case when e.entry_id is null then 1 else 0 end) no_entry,
 sum(case when e.simplified = c.title then 1 else 0 end) exact_simp,
 sum(case when e.traditional = c.title then 1 else 0 end) exact_trad,
 count(*) n
from gloss_zh_wikt_candidates c left join entries e on e.entry_id=c.entry_id
"""
print("join", con.execute(q).fetchone())
print("multi-sense entries among candidates",
      con.execute("""select count(*) from gloss_zh_wikt_candidates c
      where (select count(*) from senses s where s.entry_id=c.entry_id) > 1""").fetchone()[0])
for r in con.execute("""select c.entry_id, e.simplified, c.title, c.pos, c.definition_zh, c.def_chars, c.example_count
from gloss_zh_wikt_candidates c join entries e on e.entry_id=c.entry_id
order by e.freq_rank limited""".replace("limited","limit 6")) if False else []:
    pass
for r in con.execute("""select c.entry_id, e.simplified, e.freq_rank, c.title, c.pos, c.definition_zh, c.def_chars
from gloss_zh_wikt_candidates c join entries e on e.entry_id=c.entry_id
where e.freq_rank is not null order by e.freq_rank limit 8"""):
    print(dict(r))
for r in con.execute("""select c.entry_id, e.simplified, c.pos, c.definition_zh, c.def_chars
from gloss_zh_wikt_candidates c join entries e on e.entry_id=c.entry_id
where c.def_chars between 6 and 40 order by c.def_chars limit 5"""):
    print(dict(r))
