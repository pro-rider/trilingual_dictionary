import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "build" / "dictionary.sqlite"
con = sqlite3.connect(DB)
CONCRETE = ("nature", "everyday", "transport", "technology",
            "tools_instruments", "science_medicine", "geography_environment")
print("counts by category (freq_rank not null):")
for cat, n in con.execute(
        "SELECT category, COUNT(*) FROM entries WHERE freq_rank IS NOT NULL "
        "GROUP BY category ORDER BY 2 DESC").fetchall():
    print(f"  {cat:22s} {n}")
print()
q = ("SELECT e.simplified, e.category, e.freq_rank, (SELECT s.gloss_en FROM senses s "
     "WHERE s.entry_id=e.entry_id ORDER BY s.sense_order LIMIT 1) g "
     "FROM entries e WHERE e.freq_rank IS NOT NULL AND e.category IN ({}) "
     "ORDER BY e.freq_rank LIMIT 40").format(",".join("?" for _ in CONCRETE))
for r in con.execute(q, CONCRETE):
    print("  ", r)
