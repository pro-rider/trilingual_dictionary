"""Stage the user's raw vocabulary files into words3000_candidates.

Inputs are untrusted: both spreadsheets are read defensively, every value is
normalised, and nothing is invented. English and Nepali text is only carried over
when it literally exists in the file.

    python tools/ingest_user_vocab.py --dry-run
    python tools/ingest_user_vocab.py

Never touches `entries` or `senses`; the only table written is
`words3000_candidates`.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook
from pypinyin import Style, lazy_pinyin

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
DB = BACKEND / "data" / "build" / "dictionary.sqlite"
FILE1 = Path(r"C:\Users\Administrator\Desktop\vocabulary_table.xlsx")
FILE2 = Path(r"C:\Users\Administrator\Desktop\vocabulary_table2.xlsx")
DOCS = REPO / "docs"

SOURCE_TAG = "user-raw-2026-11-12"
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
ONLY_SYMBOLS = re.compile(r"^[\W_]+$", re.UNICODE)
MOJIBAKE = re.compile(r"\ufffd|\u25a1|锟斤拷")

@dataclass
class Row:
    word: str
    pinyin: str = ""
    traditional: str = ""
    gloss_en: str = ""
    gloss_zh: str = ""
    gloss_ne: str = ""
    freq_rank: str = ""
    provenance: str = ""
    notes: list[str] = field(default_factory=list)


def norm(text) -> str:
    if text is None:
        return ""
    value = unicodedata.normalize("NFKC", str(text))
    value = value.replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def clean_headword(text) -> tuple[str, str]:
    """Return (headword, rejection reason).

    Latin letters and digits are NOT a rejection reason: real entries in these
    lists are X射线, 记忆B细胞, 蛋白激酶B活化. A headword is only unusable when it
    contains no Chinese character at all, is nothing but symbols, is mojibake, or
    is so long that it is a phrase rather than a dictionary headword.
    """
    value = norm(text)
    if not value:
        return "", "empty"
    if MOJIBAKE.search(value):
        return "", "mojibake"
    value = re.sub(r"\s+", "", value)
    if "：" in value or ":" in value:
        value = value.split(":", 1)[-1]
    if not HAN.search(value):
        return "", "no_chinese_character"
    if ONLY_SYMBOLS.match(value):
        return "", "symbols_only"
    if len(value) > 20:
        return "", "over_20_characters"
    return value, ""


def pinyin_quartet(word: str, supplied: str = "") -> dict[str, str]:
    marked = norm(supplied)
    if not marked or not re.fullmatch(r"[A-Za-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüÜ\s]+", marked):
        marked = " ".join(lazy_pinyin(word, style=Style.TONE))
    numbered = " ".join(lazy_pinyin(word, style=Style.TONE3, neutral_tone_with_five=True))
    plain = " ".join(lazy_pinyin(word, style=Style.NORMAL))
    search = f"{plain} {plain.replace(' ', '')}".strip()
    return {"pinyin_marked": marked.lower(), "pinyin_num": numbered,
            "pinyin_plain": plain, "pinyin_search": search}


def read_file1() -> tuple[list[Row], list[dict], dict]:
    wb = load_workbook(FILE1, read_only=True, data_only=True)
    stats = {"sheets": wb.sheetnames}
    rows: list[Row] = []
    rejected: list[dict] = []
    ws = wb["词表"]
    header = [norm(c) for c in next(ws.iter_rows(max_row=1, values_only=True))]

    def col(*needles: str) -> int | None:
        """Find a column by prefix, so full-width vs half-width parentheses,
        trailing spaces and a stray '(AI 生成)' suffix cannot break the mapping."""
        for index, name in enumerate(header):
            if any(name.startswith(needle) for needle in needles):
                return index
        return None

    columns = {
        "word": col("词条", "词"),
        "pinyin": col("拼音"),
        "traditional": col("繁体"),
        "en": col("英文释义"),
        "ne": col("现有尼泊尔语"),
        "freq": col("词频排名"),
    }
    missing = [key for key, index in columns.items() if index is None and key != "freq"]
    if missing:
        raise SystemExit(f"{FILE1.name}: cannot locate columns {missing} in {header}")

    stats["columns"] = len(header)
    stats["header"] = header
    stats["mapping"] = {k: (header[i] if i is not None else None) for k, i in columns.items()}
    stats["raw_rows"] = ws.max_row - 1

    def value_of(row_values: list, key: str) -> str:
        index = columns[key]
        if index is None or index >= len(row_values):
            return ""
        return norm(row_values[index])

    for raw in ws.iter_rows(min_row=2, values_only=True):
        row_values = list(raw)
        word, reason = clean_headword(value_of(row_values, "word"))
        if reason:
            rejected.append({"file": FILE1.name, "raw": value_of(row_values, "word"),
                             "reason": reason})
            continue
        rows.append(Row(
            word=word,
            pinyin=value_of(row_values, "pinyin"),
            traditional=value_of(row_values, "traditional"),
            gloss_en=value_of(row_values, "en"),
            gloss_ne=value_of(row_values, "ne"),
            freq_rank=value_of(row_values, "freq"),
            provenance="vocabulary_table.xlsx:词表",
        ))
    stats["other_sheets"] = {}
    for name in wb.sheetnames:
        if name != "词表":
            stats["other_sheets"][name] = wb[name].max_row
    wb.close()
    return rows, rejected, stats


def read_file2() -> tuple[list[Row], list[dict], dict]:
    wb = load_workbook(FILE2, read_only=True, data_only=True)
    ws = wb["Sheet1"]
    stats = {"sheets": wb.sheetnames, "columns": ws.max_column, "raw_rows": ws.max_row}
    rows: list[Row] = []
    rejected: list[dict] = []
    raw = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()

    triples = 0
    bare = 0
    for row in raw:
        cells = [norm(c) for c in row]
        for index, cell in enumerate(cells):
            if cell.startswith("Chinese:"):
                word, reason = clean_headword(cell.split(":", 1)[1])
                if reason:
                    rejected.append({"file": FILE2.name, "raw": cell, "reason": reason})
                else:
                    rows.append(Row(word=word, provenance="vocabulary_table2.xlsx:grid"))
                    bare += 1
                continue
            if not cell:
                continue
            nxt = cells[index + 1] if index + 1 < len(cells) else ""
            nxt2 = cells[index + 2] if index + 2 < len(cells) else ""
            looks_pinyin = bool(re.fullmatch(r"[A-Za-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüÜ\s]{2,32}", nxt))
            if looks_pinyin and len(nxt2) >= 4 and HAN.search(nxt2):
                word, reason = clean_headword(cell)
                if reason:
                    rejected.append({"file": FILE2.name, "raw": cell, "reason": reason})
                    continue
                rows.append(Row(word=word, pinyin=nxt, gloss_zh=nxt2,
                                provenance="vocabulary_table2.xlsx:triple"))
                triples += 1
    stats["grid_words"] = bare
    stats["triples"] = triples
    return rows, rejected, stats


def richness(row: Row) -> tuple:
    return (bool(row.gloss_zh), bool(row.gloss_en), bool(row.gloss_ne), len(row.pinyin))


def merge(rows: list[Row]) -> tuple[list[Row], int]:
    best: dict[str, Row] = {}
    duplicates = 0
    for row in rows:
        current = best.get(row.word)
        if current is None:
            best[row.word] = row
            continue
        duplicates += 1
        if richness(row) >= richness(current):
            # keep the richer row but never drop a field the other row had
            merged = Row(
                word=row.word,
                pinyin=row.pinyin or current.pinyin,
                traditional=current.traditional or row.traditional,
                gloss_en=row.gloss_en or current.gloss_en,
                gloss_zh=row.gloss_zh or current.gloss_zh,
                gloss_ne=row.gloss_ne or current.gloss_ne,
                freq_rank=current.freq_rank or row.freq_rank,
                provenance=current.provenance + "+" + row.provenance,
            )
            best[row.word] = merged
    return list(best.values()), duplicates


def classify(row: Row) -> str:
    if row.gloss_zh:
        return "glossed_zh_only"
    if row.gloss_en or row.gloss_ne:
        return "glossed"
    return "pending_gloss"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    rows1, rej1, stats1 = read_file1()
    rows2, rej2, stats2 = read_file2()
    merged, duplicates = merge(rows1 + rows2)

    print(f"file1 {FILE1.name}: {stats1['raw_rows']:,} data rows, "
          f"{stats1['columns']} columns, usable {len(rows1):,}, rejected {len(rej1):,}")
    print(f"file2 {FILE2.name}: grid words {stats2['grid_words']:,}, "
          f"triples {stats2['triples']:,}, rejected {len(rej2):,}")
    print(f"unique headwords after dedupe: {len(merged):,} "
          f"(collisions merged: {duplicates:,})")

    con = sqlite3.connect(f"file:{DB}?mode=rw", uri=True)
    existing = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT word, status, gloss_zh FROM words3000_candidates")}
    dict_words = set(r[0] for r in con.execute("SELECT simplified FROM entries"))
    dict_no_zh = set(r[0] for r in con.execute(
        "SELECT e.simplified FROM entries e JOIN senses s ON s.entry_id=e.entry_id "
        "WHERE s.gloss_zh IS NOT NULL AND s.gloss_zh <> '' GROUP BY e.simplified"))

    inserted = {"glossed_zh_only": 0, "pending_gloss": 0, "glossed": 0}
    upgraded = 0
    skipped_existing = 0
    conflicts_in_dict = []
    conflicts_usable_zh = []
    audit_path = DOCS / f"ingest_user_vocab_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"

    if not args.dry_run:
        for row in merged:
            status = classify(row)
            if row.word in dict_words:
                conflicts_in_dict.append({"word": row.word, "status": status,
                                          "source": row.provenance})
                if row.gloss_zh and row.word not in dict_no_zh:
                    conflicts_usable_zh.append(
                        {"word": row.word, "gloss_zh": row.gloss_zh})
                continue
            if row.word in existing:
                old_status, old_zh = existing[row.word]
                if row.gloss_zh and not old_zh and old_status == "pending_gloss":
                    con.execute(
                        "UPDATE words3000_candidates SET gloss_zh=?, status=?, "
                        "pinyin=COALESCE(NULLIF(pinyin,''), ?) WHERE word=?",
                        (row.gloss_zh, status, row.pinyin, row.word))
                    upgraded += 1
                else:
                    skipped_existing += 1
                continue
            quartet = pinyin_quartet(row.word, row.pinyin)
            con.execute(
                "INSERT INTO words3000_candidates "
                "(word, pinyin, char_count, gloss_en, gloss_zh, gloss_ne, status, source) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (row.word, quartet["pinyin_marked"], len(row.word),
                 row.gloss_en or None, row.gloss_zh or None, row.gloss_ne or None,
                 status, SOURCE_TAG))
            inserted[status] += 1
            with audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "word": row.word, "status": status, "source": row.provenance,
                    **quartet,
                }, ensure_ascii=False) + "\n")
        con.commit()
    else:
        for row in merged:
            status = classify(row)
            if row.word in dict_words:
                conflicts_in_dict.append({"word": row.word, "status": status,
                                          "source": row.provenance})
                if row.gloss_zh and row.word not in dict_no_zh:
                    conflicts_usable_zh.append(
                        {"word": row.word, "gloss_zh": row.gloss_zh})
                continue
            if row.word in existing:
                skipped_existing += 1
                continue
            inserted[status] += 1

    total = con.execute("SELECT COUNT(*) FROM words3000_candidates").fetchone()[0]
    by_status = dict(con.execute(
        "SELECT status, COUNT(*) FROM words3000_candidates GROUP BY status"))
    con.close()

    rejected = rej1 + rej2
    rej_path = DOCS / "ingest_user_vocab_rejected.jsonl"
    if not args.dry_run and rejected:
        with rej_path.open("w", encoding="utf-8") as handle:
            for item in rejected:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\nsource tag      {SOURCE_TAG}")
    print(f"inserted        glossed_zh_only {inserted['glossed_zh_only']:,}  "
          f"pending_gloss {inserted['pending_gloss']:,}  glossed {inserted['glossed']:,}")
    print(f"upgraded        {upgraded:,}  (existing pending row gained a Chinese gloss)")
    print(f"skipped         {skipped_existing:,} (already staged, no richer data)")
    print(f"already in dict {len(conflicts_in_dict):,}  "
          f"(of which carry a usable Chinese gloss: {len(conflicts_usable_zh):,})")
    print(f"rejected        {len(rejected):,}")
    print(f"table now       {total:,} rows  {by_status}")
    if args.dry_run:
        print("dry run: nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
