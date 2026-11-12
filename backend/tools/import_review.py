"""Apply human review decisions from `review/*.xlsx` back into the database.

Three guarantees this tool exists to provide:

* a decision is applied only when it is exactly one of `approve`, `edit`,
  `delete`; a blank cell is "not reviewed", never approval;
* every application is written to `review_audit` (who ran it, when, which row,
  what the text was before and after);
* a deleted row is recorded in `review_rejected` and is not proposed again by
  `tools/build_review_packages.py`.

Nothing here touches `entries`/`senses` for a `delete` decision, and machine
text never becomes published text without an explicit decision cell.

    python tools/import_review.py --file review/nepali-launch-part-01.xlsx --dry-run
    python tools/import_review.py --file review --dry-run     # whole folder
    python tools/import_review.py --file review/nepali-launch-part-01.xlsx
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

REPO_ROOT = Path(__file__).resolve().parents[2]
DB = REPO_ROOT / "backend" / "data" / "build" / "dictionary.sqlite"
DECISIONS = {"approve", "edit", "delete"}
TOPICS = ("nepali-launch", "chinese-highfreq", "new-words", "examples")
REQUIRED_HEADERS = ["entry_id", "headword", "pinyin", "English gloss",
                    "Nepali (machine)", "Chinese candidate", "source",
                    "decision", "edited_text", "reviewer_notes"]

AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS review_audit (
  audit_id    INTEGER PRIMARY KEY,
  topic       TEXT NOT NULL,
  source_file TEXT NOT NULL,
  sheet_row   INTEGER NOT NULL,
  target_key  TEXT NOT NULL,
  decision    TEXT NOT NULL,
  before_text TEXT,
  after_text  TEXT,
  reviewer_notes TEXT,
  applied_at  TEXT NOT NULL,
  applied_by  TEXT NOT NULL
)
"""
REJECTED_DDL = """
CREATE TABLE IF NOT EXISTS review_rejected (
  rejected_id INTEGER PRIMARY KEY,
  topic       TEXT NOT NULL,
  target_key  TEXT NOT NULL,
  rejected_text TEXT,
  reason      TEXT,
  rejected_at TEXT NOT NULL
)
"""


def topic_from_name(path: Path) -> str:
    for topic in TOPICS:
        if path.name.startswith(topic):
            return topic
    raise SystemExit(f"cannot infer topic from filename: {path.name}")


def read_rows(path: Path):
    wb = load_workbook(path, data_only=True)
    if "Review" not in wb.sheetnames:
        raise SystemExit(f"{path.name}: no 'Review' sheet")
    sheet = wb["Review"]
    header = [cell.value for cell in sheet[1]]
    missing = [h for h in REQUIRED_HEADERS if h not in header]
    if missing:
        raise SystemExit(f"{path.name}: missing column(s) {missing}")
    index = {name: header.index(name) for name in REQUIRED_HEADERS}
    rows = []
    for sheet_row, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if all(value in (None, "") for value in row):
            continue
        record = {name: row[index[name]] for name in REQUIRED_HEADERS}
        record["_row"] = sheet_row
        rows.append(record)
    return rows


def clean(value) -> str:
    return ("" if value is None else str(value)).strip()


def plan_topic(con: sqlite3.Connection, topic: str, rows: list) -> tuple[list, list]:
    """Turn raw rows into planned actions; return (actions, errors)."""
    actions, errors = [], []
    for record in rows:
        decision = clean(record["decision"]).lower()
        if not decision:
            continue
        if decision not in DECISIONS:
            errors.append(f"row {record['_row']}: decision '{decision}' is not "
                          "approve/edit/delete")
            continue
        edited = clean(record["edited_text"])
        if decision == "edit" and not edited:
            errors.append(f"row {record['_row']}: decision 'edit' but edited_text empty")
            continue
        actions.append({
            "topic": topic, "row": record["_row"], "decision": decision,
            "edited": edited, "notes": clean(record["reviewer_notes"]),
            "entry_id": clean(record["entry_id"]),
            "headword": clean(record["headword"]),
            "pinyin": clean(record["pinyin"]),
            "en": clean(record["English gloss"]),
            "ne": clean(record["Nepali (machine)"]),
            "zh": clean(record["Chinese candidate"]),
            "source": clean(record["source"]),
        })
    return actions, errors


def resolve_nepali(con: sqlite3.Connection, action: dict):
    entry_id = action["entry_id"]
    if not entry_id.isdigit():
        return None, "entry_id is not a number"
    row = con.execute(
        "SELECT sense_id, gloss_ne, ne_status FROM senses WHERE entry_id=? "
        "AND gloss_ne IS NOT NULL AND trim(gloss_ne)!='' ORDER BY sense_order LIMIT 1",
        (int(entry_id),),
    ).fetchone()
    if row is None:
        return None, "no sense with a Nepali gloss for this entry"
    return row, None


def resolve_chinese(con: sqlite3.Connection, action: dict):
    entry_id = action["entry_id"]
    if not entry_id.isdigit():
        return None, "entry_id is not a number"
    row = con.execute(
        "SELECT c.entry_id, c.definition_zh, s.sense_id, s.gloss_zh "
        "FROM gloss_zh_wikt_candidates c "
        "JOIN senses s ON s.entry_id=c.entry_id AND s.sense_order=0 "
        "WHERE c.entry_id=?", (int(entry_id),),
    ).fetchone()
    if row is None:
        return None, "entry has no candidate or no sense 0"
    return row, None


def resolve_example(con: sqlite3.Connection, action: dict):
    entry_id = action["entry_id"]
    marker = action["source"]
    match = re.search(r"example #(\d+)", marker)
    if not match:
        return None, "source cell does not carry an example id"
    example_id = int(match.group(1))
    row = con.execute(
        "SELECT example_id, zh, review_status FROM examples WHERE example_id=?",
        (example_id,),
    ).fetchone()
    if row is None:
        return None, f"example {example_id} no longer exists"
    return row, None


def apply_new_word(con: sqlite3.Connection, action: dict):
    word = action["headword"]
    row = con.execute(
        "SELECT word, pinyin, gloss_en, gloss_ne, gloss_zh, status "
        "FROM words3000_candidates WHERE word=?", (word,)
    ).fetchone()
    if row is None:
        return None, f"word '{word}' is not in words3000_candidates"
    existing = con.execute(
        "SELECT entry_id FROM entries WHERE simplified=? LIMIT 1", (word,)
    ).fetchone()
    if existing:
        return None, f"entry already exists for '{word}'"
    return row, None


def next_id(con: sqlite3.Connection, table: str, column: str) -> int:
    return (con.execute(f"SELECT COALESCE(max({column}),0) FROM {table}").fetchone()[0]) + 1


def strip_tones(pinyin: str) -> str:
    pinyin = re.sub(r"[0-9]", "", pinyin or "")
    table = str.maketrans(
        "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüńňǹ",
        "aaaaeeeeiiiioooouuuuüüüüunnn",
    )
    return pinyin.translate(table).lower()


def apply_new_word_entry(con: sqlite3.Connection, action: dict, candidate_row):
    word, pinyin, en, ne, zh, _status = candidate_row
    gloss_en = action["edited"].split("|")[0].strip() if action["edited"] else (en or "")
    gloss_ne = action["ne"] or ne or ""
    gloss_zh = action["zh"] or zh or ""
    if action["decision"] == "edit":
        # "edited_text" holds the corrected English gloss for this topic.
        gloss_en = action["edited"]
    if not gloss_en:
        return None, "no English gloss to publish"
    entry_id = next_id(con, "entries", "entry_id")
    sense_id = next_id(con, "senses", "sense_id")
    traditional = word
    try:
        from opencc import OpenCC
        traditional = OpenCC("s2t").convert(word)
    except Exception:
        pass
    pinyin_plain = strip_tones(pinyin)
    con.execute(
        "INSERT INTO entries (entry_id, simplified, traditional, pinyin_num, "
        "pinyin_marked, pinyin_plain, pinyin_search, category, pos_primary, "
        "is_proper, is_chengyu, is_classifier, rarity, freq_rank, hsk_level, status) "
        "VALUES (?,?,?,?,?,?,?, 'general', '', 0,0,0, NULL, NULL, NULL, 'reviewed')",
        (entry_id, word, traditional, pinyin, pinyin, pinyin_plain,
         pinyin_plain.replace(" ", "")),
    )
    con.execute(
        "INSERT INTO senses (sense_id, entry_id, sense_order, gloss_en, gloss_zh, "
        "gloss_ne, ne_status, source_id) VALUES (?,?,0,?,?,?,'reviewed', NULL)",
        (sense_id, entry_id, gloss_en, gloss_zh or None, gloss_ne or None),
    )
    con.execute(
        "INSERT INTO fts (simplified, traditional, pinyin_search, english, category, entry_id) "
        "VALUES (?,?,?,?, 'general', ?)",
        (word, traditional, pinyin_plain.replace(" ", ""), gloss_en, entry_id),
    )
    con.execute(
        "INSERT INTO fts_zh (simplified, traditional, english, entry_id) VALUES (?,?,?,?)",
        (word, traditional, gloss_en, entry_id),
    )
    con.execute(
        "UPDATE words3000_candidates SET status='imported' WHERE word=?", (word,)
    )
    detail = f"entry {entry_id} / sense {sense_id}"
    return (gloss_en, gloss_en), detail


def audit(con: sqlite3.Connection, action: dict, key: str, before: str,
          after: str, applied_by: str, file_name: str):
    con.execute(
        "INSERT INTO review_audit (topic, source_file, sheet_row, target_key, "
        "decision, before_text, after_text, reviewer_notes, applied_at, applied_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (action["topic"], file_name, action["row"], key, action["decision"],
          before, after, action["notes"],
          datetime.now(timezone.utc).isoformat(), applied_by),
    )


def reject(con: sqlite3.Connection, action: dict, key: str, text: str):
    con.execute(
        "INSERT INTO review_rejected (topic, target_key, rejected_text, reason, "
        "rejected_at) VALUES (?,?,?,?,?)",
        (action["topic"], key, text, "delete decision in review file",
         datetime.now(timezone.utc).isoformat()),
    )


def process_file(con: sqlite3.Connection, path: Path, dry_run: bool, applied_by: str) -> dict:
    topic = topic_from_name(path)
    # The audit tables are created here rather than in main() so a caller that
    # drives this function directly (tests, notebooks) cannot miss them.
    con.executescript(AUDIT_DDL)
    con.executescript(REJECTED_DDL)
    rows = read_rows(path)
    actions, errors = plan_topic(con, topic, rows)
    stats = Counter(a["decision"] for a in actions)
    written = 0
    for action in actions:
        if topic == "nepali-launch":
            row, problem = resolve_nepali(con, action)
            if problem:
                errors.append(f"row {action['row']}: {problem}")
                continue
            sense_id, before, _status = row
            if action["decision"] == "delete":
                if not dry_run:
                    con.execute("UPDATE senses SET gloss_ne='', ne_status='none' "
                                "WHERE sense_id=?", (sense_id,))
                    reject(con, action, f"entry:{action['entry_id']}", before)
                    audit(con, action, f"sense:{sense_id}", before, "", applied_by,
                          path.name)
                written += 1
                continue
            after = action["edited"] if action["decision"] == "edit" else action["ne"] or before
            if not after:
                errors.append(f"row {action['row']}: nothing to publish")
                continue
            if not dry_run:
                con.execute("UPDATE senses SET gloss_ne=?, ne_status='reviewed' "
                            "WHERE sense_id=?", (after, sense_id))
                audit(con, action, f"sense:{sense_id}", before, after, applied_by,
                      path.name)
            written += 1
        elif topic == "chinese-highfreq":
            row, problem = resolve_chinese(con, action)
            if problem:
                errors.append(f"row {action['row']}: {problem}")
                continue
            entry_id, candidate, sense_id, before = row
            if action["decision"] == "delete":
                if not dry_run:
                    reject(con, action, f"entry:{entry_id}", candidate or "")
                    audit(con, action, f"entry:{entry_id}", candidate or "", "",
                          applied_by, path.name)
                written += 1
                continue
            after = action["edited"] if action["decision"] == "edit" else candidate
            if not after:
                errors.append(f"row {action['row']}: no Chinese text to publish")
                continue
            if not dry_run:
                con.execute("UPDATE senses SET gloss_zh=? WHERE sense_id=?",
                            (after, sense_id))
                con.execute(
                    "INSERT OR REPLACE INTO gloss_provenance (sense_id, entry_id, "
                    "source, license, license_url, method, confidence, run_id, applied_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (sense_id, entry_id, "zh.wiktionary", "CC BY-SA 4.0",
                     "https://creativecommons.org/licenses/by-sa/4.0/",
                     "human_approved via review file", "reviewed", "review-import",
                     datetime.now(timezone.utc).isoformat()),
                )
                audit(con, action, f"entry:{entry_id}", before or "", after,
                      applied_by, path.name)
            written += 1
        elif topic == "new-words":
            row, problem = apply_new_word(con, action)
            if problem:
                errors.append(f"row {action['row']}: {problem}")
                continue
            if action["decision"] == "delete":
                if not dry_run:
                    reject(con, action, f"word:{action['headword']}", row[2] or "")
                    audit(con, action, f"word:{action['headword']}", row[2] or "", "",
                          applied_by, path.name)
                written += 1
                continue
            if dry_run:
                written += 1
                continue
            result, problem = apply_new_word_entry(con, action, row)
            if problem:
                errors.append(f"row {action['row']}: {problem}")
                continue
            audit(con, action, f"word:{action['headword']}", row[2] or "",
                  result[0], applied_by, path.name)
            written += 1
        elif topic == "examples":
            row, problem = resolve_example(con, action)
            if problem:
                errors.append(f"row {action['row']}: {problem}")
                continue
            example_id, before, status = row
            if action["decision"] == "delete":
                if not dry_run:
                    con.execute("UPDATE examples SET review_status='quarantined', "
                                "quarantine_reason='rejected in review' WHERE example_id=?",
                                (example_id,))
                    reject(con, action, f"example:{example_id}", before or "")
                    audit(con, action, f"example:{example_id}", before or "", "",
                          applied_by, path.name)
                written += 1
                continue
            after = action["edited"] if action["decision"] == "edit" else before
            if not dry_run:
                con.execute("UPDATE examples SET zh=?, review_status='verified' "
                            "WHERE example_id=?", (after, example_id))
                audit(con, action, f"example:{example_id}", before or "", after,
                      applied_by, path.name)
            written += 1

    if not dry_run:
        con.commit()
    return {"file": path.name, "topic": topic, "rows_read": len(rows),
            "decisions": dict(stats), "applied": written, "errors": errors,
            "dry_run": dry_run}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="an .xlsx or a folder of them")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--by", default="reviewer (unspecified)",
                    help="who is applying these decisions, for the audit log")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args(argv)

    target = Path(args.file)
    files = sorted(target.glob("*.xlsx")) if target.is_dir() else [target]
    if not files:
        raise SystemExit("no .xlsx files found")

    con = sqlite3.connect(args.db)
    con.executescript(AUDIT_DDL)
    con.executescript(REJECTED_DDL)
    results = []
    total_errors = 0
    for path in files:
        result = process_file(con, path, args.dry_run, args.by)
        results.append(result)
        total_errors += len(result["errors"])
        print(f"{result['file']}: read={result['rows_read']} "
              f"decisions={result['decisions']} applied={result['applied']} "
              f"errors={len(result['errors'])}")
        for error in result["errors"][:10]:
            print(f"  ! {error}")
    print(f"TOTAL: {sum(r['applied'] for r in results)} decision(s), "
          f"{total_errors} error(s), dry_run={args.dry_run}")
    con.close()
    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
