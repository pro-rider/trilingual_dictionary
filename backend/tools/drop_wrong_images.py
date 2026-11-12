"""Remove four image links that a human read as wrong, with the reason kept.

The lexical gate cannot tell "a photograph of the subject" from "a photograph
that happens to be filed near it". These four passed the gate and still fail the
"would a reader accept this?" test, so they are dropped rather than shipped:

  114  history        <- a Dutch still life (hourglass and inkpot)
  115  people         <- a photograph of one Austrian folk ride
  145  network management <- a Cacti monitoring screenshot
  146  jargon         <- an untitled personal photograph

Deleting the link removes the picture from that word; deleting the image row and
file keeps `verify_image_assets.py` free of orphans.
"""

import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "backend" / "data" / "build" / "dictionary.sqlite"

DROP = {
    114: "a Dutch still life cannot illustrate 历史 (history)",
    115: "one folk ride photograph cannot illustrate 人们 (people)",
    145: "a Cacti screenshot is not a picture of 网络管理 (network management)",
    146: "an untitled personal photograph cannot illustrate 行话 (jargon)",
}

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
for image_id, why in DROP.items():
    entries = con.execute(
        "SELECT GROUP_CONCAT(e.simplified) FROM entry_images ei "
        "JOIN entries e ON e.entry_id=ei.entry_id WHERE ei.image_id=?",
        (image_id,)).fetchone()[0]
    if not entries:
        print(f"image {image_id}: already unreferenced")
        continue
    con.execute("DELETE FROM entry_images WHERE image_id=?", (image_id,))
    con.execute("DELETE FROM concept_images WHERE image_id=?", (image_id,))
    asset = con.execute("SELECT thumb_asset FROM images WHERE image_id=?",
                        (image_id,)).fetchone()[0]
    if asset and (REPO / asset).is_file():
        (REPO / asset).unlink()
    con.execute("DELETE FROM images WHERE image_id=?", (image_id,))
    print(f"image {image_id} removed for {entries}: {why}")
con.execute("DELETE FROM concepts WHERE concept_id NOT IN "
            "(SELECT concept_id FROM concept_images)")
con.commit()
print("images now:", con.execute("SELECT COUNT(*) FROM images").fetchone()[0])
print("entries with a picture:",
      con.execute("SELECT COUNT(DISTINCT entry_id) FROM entry_images").fetchone()[0])
