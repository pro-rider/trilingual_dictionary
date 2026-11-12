"""Precision audit of the 113 shipped image links (substring, not token equality).

A token comparison wrongly condemned "FullMoon2010.jpg" for the gloss "moon",
because "fullmoon" is one token. Matching a gloss word as a *substring* of the
lower-cased title is the right test for filenames, which are often camel-cased.
This only reports; it never deletes.
"""

import re
import sqlite3

WORD = re.compile(r"[A-Za-z]{3,}")
STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "your", "you",
        "are", "was", "old", "variant", "and"}

con = sqlite3.connect("data/build/dictionary.sqlite")
con.row_factory = sqlite3.Row
rows = con.execute(
    "SELECT ei.entry_id, e.simplified, ei.image_id, ei.match_method, i.title, "
    "       (SELECT gloss_en FROM senses s WHERE s.entry_id=e.entry_id "
    "        ORDER BY s.sense_order LIMIT 1) AS gloss "
    "FROM entry_images ei JOIN entries e ON e.entry_id=ei.entry_id "
    "JOIN images i ON i.image_id=ei.image_id ORDER BY ei.image_id").fetchall()

suspect = []
for row in rows:
    gloss = (row["gloss"] or "").lower()
    title = (row["title"] or "").lower()
    words = [w for w in WORD.findall(gloss) if w not in STOP]
    if not words:
        suspect.append((row, "no gloss words"))
        continue
    if not any(w in title for w in words):
        suspect.append((row, "no gloss word in title"))

print(f"links {len(rows)}   flagged {len(suspect)}")
for row, why in suspect:
    print(f"  {row['simplified']} (id {row['entry_id']}) <- image {row['image_id']} "
          f"[{row['match_method']}] '{(row['title'] or '')[:45]}' gloss='{row['gloss']}' ({why})")
