"""What 90% coverage actually costs, from the database itself.

Answers three questions with measured inputs rather than optimism:
  1. how many entries could display a photograph at all;
  2. how many acquisition attempts 90% of each frequency band needs;
  3. how long that takes at the throughput this machine really achieves.
"""

import sqlite3

CON_MS = 20500  # measured: ~20.5 s per word end-to-end (single process)
ACCEPT = 0.55   # measured acceptance on concrete nouns

con = sqlite3.connect("data/build/dictionary.sqlite")

total = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
covered = con.execute("SELECT COUNT(DISTINCT entry_id) FROM entry_images").fetchone()[0]
nouns = con.execute("SELECT COUNT(*) FROM entries WHERE pos_primary='n'").fetchone()[0]
noun_like = con.execute(
    "SELECT COUNT(*) FROM entries WHERE pos_primary IN ('n','nr','ns','nz','vn')").fetchone()[0]

print(f"entries {total:,}  with picture {covered:,} ({covered/total*100:.2f}%)")
print(f"entries tagged noun {nouns:,}  noun-like {noun_like:,}")

for band in (500, 1000, 5000, 20000):
    n, cov = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT entry_id) FROM ("
        "  SELECT e.entry_id FROM entries e WHERE e.freq_rank <= ?) q "
        "JOIN entry_images ei ON ei.entry_id = q.entry_id", (band,)).fetchone() if False else (0, 0)
    n = con.execute("SELECT COUNT(*) FROM entries WHERE freq_rank <= ?", (band,)).fetchone()[0]
    cov = con.execute(
        "SELECT COUNT(DISTINCT e.entry_id) FROM entries e JOIN entry_images ei "
        "ON ei.entry_id=e.entry_id WHERE e.freq_rank <= ?", (band,)).fetchone()[0]
    need = int(n * 0.9) - cov
    attempts = int(max(need, 0) / ACCEPT)
    hours = attempts * CON_MS / 1000 / 3600
    print(f"top {band:>6}: entries {n:6,}  covered {cov:5,} ({cov/n*100:5.2f}%)  "
          f"need {max(need,0):6,}  attempts {attempts:7,}  ~{hours:6.1f} h")

allneed = int(total * 0.9) - covered
print(f"\n90% of every entry needs {allneed:,} more pictures; "
      f"noun-like entries available: {noun_like - covered:,}")
print(f"at {ACCEPT:.0%} acceptance and {CON_MS/1000:.1f} s/attempt: "
      f"{allneed/ACCEPT*CON_MS/1000/86400:,.1f} days of continuous crawling")
print(f"at 8 KB per thumbnail, {allneed:,} pictures = {allneed*8/1048576:,.1f} MB of thumbnails")
