import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite")
con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)


def show(label, sql):
    print(label)
    for row in con.execute(sql).fetchall():
        print("  ", row)


show("by pos", "select pos, count(*) from gloss_zh_wikt_candidates group by pos order by 2 desc limit 15")
show("chars buckets", """
select case when def_chars<=0 then '0' when def_chars<=5 then '1-5' when def_chars<=15 then '6-15'
when def_chars<=40 then '16-40' when def_chars<=100 then '41-100' else '100+' end b, count(*)
from gloss_zh_wikt_candidates group by b order by 1""")
show("license/source", "select license, source, count(*) from gloss_zh_wikt_candidates group by 1,2")
show("join", """select sum(case when e.entry_id is null then 1 else 0 end) no_entry,
 sum(case when e.simplified=c.title then 1 else 0 end) exact_simp,
 sum(case when e.traditional=c.title then 1 else 0 end) exact_trad, count(*) n
from gloss_zh_wikt_candidates c left join entries e on e.entry_id=c.entry_id""")
show("junk pattern", """select count(*) from gloss_zh_wikt_candidates
where definition_zh like '%{{%' or definition_zh like '%[[%' or definition_zh like '%ref=%'""")
show("suspicious starts", """select substr(definition_zh,1,2) p, count(*) from gloss_zh_wikt_candidates
where substr(definition_zh,1,2) in ('见','参','另','同','即','《','（') group by p order by 2 desc""")
show("cand in launch tier12", """select l.tier, count(*) from gloss_zh_wikt_candidates c join launch_set l using(entry_id) group by l.tier""")
show("cand by freq bucket", """select case when e.freq_rank is null then 'null' when e.freq_rank<=10000 then '1-10k'
when e.freq_rank<=20000 then '10k-20k' else '>20k' end b, count(*) from gloss_zh_wikt_candidates c join entries e using(entry_id) group by b""")
show("sense count dist among cands", """select ns, count(*) from (select (select count(*) from senses s where s.entry_id=c.entry_id) ns from gloss_zh_wikt_candidates c) group by ns order by ns limit 10""")
show("single sense cands", """select count(*) from gloss_zh_wikt_candidates c
where (select count(*) from senses s where s.entry_id=c.entry_id)=1""")
