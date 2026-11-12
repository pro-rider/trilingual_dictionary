"""Build the human review packages in `review/`.

Four topics, one workbook per 500 rows, each workbook carrying a README sheet
that explains exactly how to fill it in. The data sheet is always named
`Review` so `tools/import_review.py` can find it without guessing.

    python tools/build_review_packages.py
    python tools/build_review_packages.py --chunk 300 --out review
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

REPO_ROOT = Path(__file__).resolve().parents[2]
DB = REPO_ROOT / "backend" / "data" / "build" / "dictionary.sqlite"
OUT = REPO_ROOT / "review"

COLUMNS = [
    ("entry_id", 10),
    ("headword", 14),
    ("pinyin", 14),
    ("English gloss", 34),
    ("Nepali (machine)", 28),
    ("Chinese candidate", 34),
    ("source", 22),
    ("decision", 12),
    ("edited_text", 32),
    ("reviewer_notes", 30),
]

TOPICS = {
    "nepali-launch": (
        "Nepali review — launch set (2,477 HSK + 2,523 most frequent words). "
        "Every Nepali gloss here is machine output (llama-3.1-70b via OpenRouter) "
        "and has never been read by a native speaker.",
        "approve → the gloss is published as reviewed. edit → put your replacement "
        "in `edited_text`. delete → the row keeps an empty Nepali gloss and is "
        "never re-proposed. A gloss of '-' means nothing was filled.",
    ),
    "chinese-highfreq": (
        "Chinese definitions for the top-10,000 words, deliberately NOT auto-imported. "
        "For these words the Wiktionary gloss usually lists classical meanings first "
        "(的 → white / target centre / standard), which is wrong for a learner.",
        "approve → the candidate text becomes the published Chinese definition. "
        "edit → put a learner-appropriate definition in `edited_text`. "
        "delete → the sense stays without a Chinese definition.",
    ),
    "new-words": (
        "The 1,348 new words that are not in CC-CEDICT. 320 came from the earlier "
        "human-translated batch; the rest are machine-generated and unreviewed.",
        "approve → the word becomes a real entry with one sense. edit → your text "
        "replaces the glosses. delete → the word is not added at all.",
    ),
    "examples": (
        "The 392 existing example sentences. None of them has been verified; they were "
        "imported from licensed data or generated.",
        "approve → the example is marked verified and may be shown. edit → your "
        "sentence replaces it. delete → the example is quarantined and hidden.",
    ),
}

HEADER_FILL = PatternFill("solid", fgColor="E8EEF7")
README_LINES = [
    "How to fill this sheet",
    "",
    "1. Read the four data columns first: headword, pinyin, English gloss, and the",
    "   candidate text this file is about.",
    "2. In the `decision` column write exactly one of: approve, edit, delete.",
    "   Leave it blank to skip the row — blank means 'no decision yet', not approval.",
    "3. For `edit`, put the corrected text in `edited_text`. That text is what gets",
    "   published, verbatim.",
    "4. `reviewer_notes` is optional and free text. Use it for anything a second",
    "   reviewer should know.",
    "5. Save the file as .xlsx and hand it back. Import with:",
    "   python tools/import_review.py --file <this file> --dry-run",
    "   then run it again without --dry-run to apply.",
    "6. Rows you delete are recorded and will not be proposed again.",
]


def _con():
    return sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)


def rejected_keys(con, topic: str) -> set:
    """Rows a reviewer already deleted, so they are never proposed again."""
    try:
        rows = con.execute(
            "SELECT target_key FROM review_rejected WHERE topic=?", (topic,)
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {row[0] for row in rows}


def nepali_rows(con):
    rows = con.execute(
        """
        SELECT s.entry_id, e.simplified, e.pinyin_marked, s.gloss_en,
               s.gloss_ne, COALESCE(s.gloss_zh,''),
               'ai_translated (llama-3.1-70b)'
        FROM senses s
        JOIN entries e USING(entry_id)
        JOIN launch_set l USING(entry_id)
        WHERE l.tier <= 2 AND s.gloss_ne IS NOT NULL AND trim(s.gloss_ne) != ''
        ORDER BY l.tier, e.freq_rank IS NULL, e.freq_rank, e.entry_id
        """
    ).fetchall()
    return [tuple(r) + ("", "", "") for r in rows]


def chinese_rows(con):
    rows = con.execute(
        """
        SELECT c.entry_id, e.simplified, e.pinyin_marked, 
               COALESCE(s.gloss_en,''),
               COALESCE(s.gloss_ne,''),
               c.definition_zh,
               'zh.wiktionary (CC BY-SA 4.0)'
        FROM gloss_zh_wikt_candidates c
        JOIN entries e USING(entry_id)
        JOIN senses s ON s.entry_id = c.entry_id AND s.sense_order = 0
        WHERE e.freq_rank IS NOT NULL AND e.freq_rank <= 10000
        ORDER BY e.freq_rank, e.entry_id
        """
    ).fetchall()
    return [tuple(r) + ("", "", "") for r in rows]


def new_word_rows(con):
    rows = con.execute(
        """
        SELECT '' AS entry_id, w.word, w.pinyin, COALESCE(w.gloss_en,''), 
               COALESCE(w.gloss_ne,''), COALESCE(w.gloss_zh,''),
               CASE w.status WHEN 'glossed' THEN 'human batch (2026-11)'
                             WHEN 'glossed_ai' THEN 'ai: llama-3.1-70b'
                             ELSE w.status END
        FROM words3000_candidates w
        ORDER BY w.char_count, w.word
        """
    ).fetchall()
    return [tuple(r) + ("", "", "") for r in rows]


def example_rows(con):
    rows = con.execute(
        """
        SELECT s.entry_id, e.simplified, e.pinyin_marked, s.gloss_en,
               COALESCE(s.gloss_ne,''),
               TRIM(COALESCE(x.zh,'') || ' / ' || COALESCE(x.en,'')),
               'example #' || x.example_id || ' (' || x.review_status || ')'
        FROM examples x JOIN senses s USING(sense_id) JOIN entries e USING(entry_id)
        ORDER BY s.entry_id
        """
    ).fetchall()
    return [tuple(r) + ("", "", "") for r in rows]


BUILDERS = {
    "nepali-launch": nepali_rows,
    "chinese-highfreq": chinese_rows,
    "new-words": new_word_rows,
    "examples": example_rows,
}


def write_workbook(path: Path, topic: str, part: int, total_parts: int, rows: list):
    wb = Workbook()
    readme = wb.active
    readme.title = "README"
    readme.column_dimensions["A"].width = 112
    readme["A1"] = f"REVIEW PACKAGE — {topic} — part {part} of {total_parts}"
    readme["A1"].font = Font(bold=True, size=13)
    summary, instructions = TOPICS[topic]
    readme["A3"] = summary
    readme["A3"].alignment = Alignment(wrap_text=True, vertical="top")
    readme.row_dimensions[3].height = 60
    for offset, line in enumerate(README_LINES):
        readme.cell(row=5 + offset, column=1, value=line)
    readme.cell(row=5 + len(README_LINES) + 1, column=1,
                value=f"Rows in this file: {len(rows)}. Column meanings:")
    for offset, (name, width) in enumerate(COLUMNS):
        readme.cell(row=5 + len(README_LINES) + 3 + offset, column=1,
                    value=f"  {name}: {'what to write' if name in ('decision','edited_text','reviewer_notes') else 'reference data, do not edit'}")
    readme.cell(row=5 + len(README_LINES) + 2, column=1, value=instructions)

    sheet = wb.create_sheet("Review")
    for col, (name, width) in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=1, column=col, value=name)
        cell.font = Font(bold=True, color="1F2937")
        cell.fill = HEADER_FILL
        sheet.column_dimensions[get_column_letter(col)].width = width
    for row_index, row in enumerate(rows, start=2):
        for col, value in enumerate(row, start=1):
            cell = sheet.cell(row=row_index, column=col, value=value)
            cell.alignment = Alignment(wrap_text=False, vertical="top")
    sheet.freeze_panes = "A2"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", type=int, default=500)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--topic", default=None, choices=sorted(BUILDERS) + [None])
    args = ap.parse_args(argv)

    con = _con()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for topic, builder in BUILDERS.items():
        if args.topic and topic != args.topic:
            continue
        rows = builder(con)
        skipped = rejected_keys(con, topic)
        if skipped:
            kept = []
            for row in rows:
                entry_id, headword = str(row[0]), str(row[1])
                if (f"sense:{entry_id}" in skipped or f"entry:{entry_id}" in skipped
                        or f"word:{headword}" in skipped
                        or f"example:{entry_id}" in skipped):
                    continue
                kept.append(row)
            print(f"{topic}: {len(rows) - len(kept)} previously deleted row(s) withheld")
            rows = kept
        parts = max(1, -(-len(rows) // args.chunk))
        for part in range(parts):
            chunk = rows[part * args.chunk : (part + 1) * args.chunk]
            path = out / f"{topic}-part-{part + 1:02d}.xlsx"
            write_workbook(path, topic, part + 1, parts, chunk)
            manifest.append((path.name, len(chunk)))
        print(f"{topic}: {len(rows)} rows in {parts} file(s)")
    con.close()

    (out / "README.md").write_text(render_readme(manifest), encoding="utf-8")
    print(f"wrote {len(manifest)} workbook(s) + README.md to {out}")
    return 0


def render_readme(manifest) -> str:
    lines = [
        "# review/ — human review packages",
        "",
        "Everything here is machine-produced or unreviewed data waiting for a person.",
        "Nothing in this folder ships as-is; it becomes real dictionary content only",
        "after a decision is imported with `tools/import_review.py`.",
        "",
        "## How to work through it",
        "",
        "1. Open one workbook. Read its README sheet first — it says what that topic is.",
        "2. Fill the `decision` column: `approve`, `edit` (plus `edited_text`), or `delete`.",
        "   A blank decision means 'not reviewed yet' and is never treated as approval.",
        "3. Save and hand the file back. Import preview:",
        "   `python tools/import_review.py --file review/nepali-launch-part-01.xlsx --dry-run`",
        "   Apply:",
        "   `python tools/import_review.py --file review/nepali-launch-part-01.xlsx`",
        "4. Deleted rows are logged and are not proposed again in later packages.",
        "",
        "## Suggested order",
        "",
        "1. `new-words-*` — sets the policy for words that are not in CC-CEDICT.",
        "2. `examples-*` — smallest topic, teaches the format.",
        "3. `nepali-launch-*` — the largest and slowest; needs a native speaker.",
        "4. `chinese-highfreq-*` — needs a Chinese reader; highest risk of archaic senses.",
        "",
        "## What is in here",
        "",
        "| file | rows |",
        "|---|---|",
    ]
    for name, count in manifest:
        lines.append(f"| `{name}` | {count} |")
    lines += [
        "",
        "## Column contract",
        "",
        "`entry_id, headword, pinyin, English gloss, Nepali (machine), "
        "Chinese candidate, source, decision, edited_text, reviewer_notes`",
        "",
        "The import tool reads these headers by name, so do not rename them.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
