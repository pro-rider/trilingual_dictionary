"""Drop the two concept-label inheritances that a human read as wrong.

The exact-label rule is mechanical: it fires when a concept's Chinese label equals
a headword. That is right for 月球→moon and 鼓→drum, but it also fired for
时候→a pocket watch (a concrete object standing in for an abstract noun) and
鸟→an 1846 engraving of Aristophanes' play *The Birds* (the same reproduction the
quality gate already rejects when it is fetched fresh). Both are removed here so
the rule keeps its precision instead of lowering the bar to raise coverage.
"""

import sqlite3

DROP = [(52724, "时候", "a pocket watch for an abstract noun"),
        (121286, "鸟", "engraving of a play, not a photograph of a bird")]

con = sqlite3.connect("data/build/dictionary.sqlite")
for entry_id, word, why in DROP:
    n = con.execute(
        "DELETE FROM entry_images WHERE entry_id=? AND match_method='concept-label'",
        (entry_id,)).rowcount
    print(f"{word} ({entry_id}): removed {n} row(s) — {why}")
con.commit()
print("entries with picture:",
      con.execute("SELECT COUNT(DISTINCT entry_id) FROM entry_images").fetchone()[0])
