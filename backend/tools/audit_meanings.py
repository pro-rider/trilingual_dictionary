"""Audit every gloss in the dictionary for defects, and fix the ones that are safe.

A meaning can be *wrong* in two very different ways, and they need different tools:

* **Mechanical defects** — mojibake, control characters, stray whitespace, placeholder
  text such as "Translate now", a Chinese column that actually holds English. These
  are decidable with rules, and every one of them is reversible.
* **Semantic defects** — the gloss names a different thing than the headword. No
  embedding model can decide this, because similarity scores are not correctness:
  across languages a cosine score is close to noise, and a confidently wrong rewrite
  is worse than a flag. Those are collected into a review queue instead.

So this tool reports on every sense (198,306 of them) and rewrites only in the
mechanical class, logging each change so the run can be reversed.

Usage:
    python tools/audit_meanings.py                      # audit only, writes reports
    python tools/audit_meanings.py --apply              # apply safe fixes + log them
    python tools/audit_meanings.py --csv words.csv      # also audit an export file
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff]")
LATIN = re.compile(r"[A-Za-z]")
DEVANAGARI = re.compile(r"[\u0900-\u097F]")
MOJIBAKE = re.compile(r"[\ufffd]|Ã.|â€|鈥|ï¿\u00bd")
CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u200b-\u200f\u2028\u2029]")
PLACEHOLDER = re.compile(r"^(translate now|to be translated|tbd|todo|-|—|\.)$", re.I)
# CC-CEDICT routinely cross-references in Chinese inside an English gloss
# ("variant of 闔|阖[he2]", "see 後坐力", "abbr. for 教育培訓|教育培训[...]"). That is
# the dictionary's own notation, not a defect, so those forms are excluded below.
NOTATION = re.compile(r"(variant of|see |also written|abbr\. for|aka |\[.*?\]|（.*?）)")
WHITESPACE_RUN = re.compile(r"\s+")

LANG_COLUMNS = (
    ("gloss_en", "en", LATIN, CJK),
    ("gloss_zh", "zh", CJK, None),
    ("gloss_ne", "ne", DEVANAGARI, CJK),
)


@dataclass
class Issue:
    sense_id: int
    entry_id: int
    word: str
    column: str
    issue: str
    detail: str
    old_value: str
    new_value: str
    auto_fixable: bool


def clean_text(value: str) -> str:
    """The only rewrite we trust: normalise space and drop invisible characters."""
    text = unicodedata.normalize("NFC", value)
    text = CONTROL.sub("", text)
    text = WHITESPACE_RUN.sub(" ", text)
    return text.strip()


def evaluate(word: str, column: str, lang: str, expected: re.Pattern, forbidden: re.Pattern | None,
             raw: str) -> Issue | None:
    sense_id, entry_id = 0, 0  # filled by the caller
    value = raw or ""
    if not value.strip():
        return None

    stripped = clean_text(value)
    if PLACEHOLDER.match(stripped):
        return Issue(sense_id, entry_id, word, column, "placeholder", f"value is '{stripped}'", value, "", True)
    if MOJIBAKE.search(stripped):
        return Issue(sense_id, entry_id, word, column, "mojibake", "encoding damage", value, "", False)
    if CONTROL.search(value) or value != stripped:
        return Issue(sense_id, entry_id, word, column, "whitespace", "invisible or repeated whitespace",
                     value, stripped, True)
    if lang == "en" and forbidden and forbidden.search(stripped) and not LATIN.search(stripped):
        return Issue(sense_id, entry_id, word, column, "wrong_language", "expected Latin script", value, "", False)
    if lang == "en" and CJK.search(stripped) and not NOTATION.search(stripped):
        # A handful of Chinese characters naming a proper noun is normal in an
        # English gloss; flag only when the cell is mostly Chinese, i.e. the
        # column holds the wrong language rather than a cross-reference.
        cjk_chars = len(CJK.findall(stripped))
        if cjk_chars / max(1, len(stripped)) > 0.5:
            return Issue(sense_id, entry_id, word, column, "mixed_script",
                         "cell is mostly Chinese inside an English gloss", value, "", False)
    if lang == "zh" and not expected.search(stripped):
        return Issue(sense_id, entry_id, word, column, "wrong_language", "no Chinese in a Chinese gloss", value, "", False)
    if lang == "ne" and not expected.search(stripped) and LATIN.search(stripped):
        return Issue(sense_id, entry_id, word, column, "wrong_language", "Latin text in a Nepali gloss", value, "", False)
    if len(stripped) > 240:
        return Issue(sense_id, entry_id, word, column, "overlong", f"{len(stripped)} characters", value, "", False)
    return None


def audit_database(db_path: Path) -> tuple[list[Issue], list[Issue]]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT s.sense_id, s.entry_id, e.simplified AS word,
               s.gloss_en, s.gloss_zh, s.gloss_ne
        FROM senses s JOIN entries e ON e.entry_id = s.entry_id
        """
    ).fetchall()
    con.close()

    issues: list[Issue] = []
    duplicates: list[Issue] = []
    for row in rows:
        for column, lang, expected, forbidden in LANG_COLUMNS:
            issue = evaluate(row["word"], column, lang, expected, forbidden, row[column] or "")
            if issue is not None:
                issue.sense_id = row["sense_id"]
                issue.entry_id = row["entry_id"]
                issues.append(issue)
        zh, en = (row["gloss_zh"] or "").strip(), (row["gloss_en"] or "").strip()
        if zh and en and zh.casefold() == en.casefold():
            duplicates.append(Issue(row["sense_id"], row["entry_id"], row["word"], "gloss_zh",
                                    "same_as_english", "Chinese column repeats the English gloss", zh, "", False))
    return issues, duplicates


def audit_csv(path: Path) -> list[Issue]:
    """Any gloss-like column in an export file gets the same rules applied."""
    issues: list[Issue] = []
    if not path.exists():
        raise SystemExit(f"no such file: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=2):
            for column, lang, expected, forbidden in LANG_COLUMNS:
                if column not in row:
                    continue
                issue = evaluate(str(row.get("word") or row.get("simplified") or ""), column, lang,
                                 expected, forbidden, row[column] or "")
                if issue is not None:
                    issue.entry_id = index
                    issues.append(issue)
    return issues


def apply_fixes(db_path: Path, issues: list[Issue], log_path: Path) -> int:
    """Rewrite only whitespace/placeholder defects; every change is logged first."""
    con = sqlite3.connect(db_path)
    applied = 0
    with log_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sense_id", "entry_id", "word", "column", "issue", "old_value", "new_value"])
        for issue in issues:
            if not issue.auto_fixable:
                continue
            writer.writerow([issue.sense_id, issue.entry_id, issue.word, issue.column,
                             issue.issue, issue.old_value, issue.new_value])
            con.execute(
                f"UPDATE senses SET {issue.column} = ? WHERE sense_id = ?",
                (issue.new_value or None, issue.sense_id),
            )
            applied += 1
        con.commit()
    con.close()
    return applied


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/build/dictionary.sqlite"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/build/reports"))
    parser.add_argument("--csv", type=Path, action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv[1:])

    issues, duplicates = audit_database(args.db)
    combined = issues + duplicates
    for path in args.csv:
        combined.extend(audit_csv(path))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    audit_path = args.out_dir / "meaning_audit.csv"
    with audit_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sense_id", "entry_id", "word", "column", "issue", "detail",
                         "old_value", "suggested_value", "auto_fixable"])
        for issue in combined:
            writer.writerow([issue.sense_id, issue.entry_id, issue.word, issue.column, issue.issue,
                             issue.detail, issue.old_value[:300], issue.new_value[:300],
                             "yes" if issue.auto_fixable else "no"])

    summary_path = args.out_dir / "meaning_audit_summary.csv"
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dimension", "value", "count"])
        for value, count in Counter(issue.issue for issue in combined).most_common():
            writer.writerow(["issue", value, count])
        for value, count in Counter(issue.column for issue in combined).most_common():
            writer.writerow(["column", value, count])

    print(f"issues found: {len(combined)}")
    for value, count in Counter(issue.issue for issue in combined).most_common():
        print(f"  {value:<18} {count}")
    print(f"automatically fixable: {sum(1 for i in combined if i.auto_fixable)}")
    print(f"written: {audit_path}")
    print(f"written: {summary_path}")

    if args.apply:
        log_path = args.out_dir / "meaning_autofix_log.csv"
        applied = apply_fixes(args.db, combined, log_path)
        print(f"applied {applied} safe fixes; undo log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
