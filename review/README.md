# review/ — human review packages

Everything here is machine-produced or unreviewed data waiting for a person.
Nothing in this folder ships as-is; it becomes real dictionary content only
after a decision is imported with `tools/import_review.py`.

## How to work through it

1. Open one workbook. Read its README sheet first — it says what that topic is.
2. Fill the `decision` column: `approve`, `edit` (plus `edited_text`), or `delete`.
   A blank decision means 'not reviewed yet' and is never treated as approval.
3. Save and hand the file back. Import preview:
   `python tools/import_review.py --file review/nepali-launch-part-01.xlsx --dry-run`
   Apply:
   `python tools/import_review.py --file review/nepali-launch-part-01.xlsx`
4. Deleted rows are logged and are not proposed again in later packages.

## Suggested order

1. `new-words-*` — sets the policy for words that are not in CC-CEDICT.
2. `examples-*` — smallest topic, teaches the format.
3. `nepali-launch-*` — the largest and slowest; needs a native speaker.
4. `chinese-highfreq-*` — needs a Chinese reader; highest risk of archaic senses.

## What is in here

| file | rows |
|---|---|
| `nepali-launch-part-01.xlsx` | 500 |
| `nepali-launch-part-02.xlsx` | 500 |
| `nepali-launch-part-03.xlsx` | 500 |
| `nepali-launch-part-04.xlsx` | 500 |
| `nepali-launch-part-05.xlsx` | 500 |
| `nepali-launch-part-06.xlsx` | 358 |
| `chinese-highfreq-part-01.xlsx` | 500 |
| `chinese-highfreq-part-02.xlsx` | 500 |
| `chinese-highfreq-part-03.xlsx` | 500 |
| `chinese-highfreq-part-04.xlsx` | 500 |
| `chinese-highfreq-part-05.xlsx` | 500 |
| `chinese-highfreq-part-06.xlsx` | 500 |
| `chinese-highfreq-part-07.xlsx` | 500 |
| `chinese-highfreq-part-08.xlsx` | 500 |
| `chinese-highfreq-part-09.xlsx` | 500 |
| `chinese-highfreq-part-10.xlsx` | 500 |
| `chinese-highfreq-part-11.xlsx` | 140 |
| `new-words-part-01.xlsx` | 500 |
| `new-words-part-02.xlsx` | 500 |
| `new-words-part-03.xlsx` | 348 |
| `examples-part-01.xlsx` | 392 |

## Column contract

`entry_id, headword, pinyin, English gloss, Nepali (machine), Chinese candidate, source, decision, edited_text, reviewer_notes`

The import tool reads these headers by name, so do not rename them.

## Where these files live, and how to rebuild them

Canonical path:
`C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\review\`
(21 workbooks, 9,738 data rows, 1,194,560 B at the last build; re-verified on
2026-11-12 with `tools/verify_review_packages.py` → `ALL WORKBOOKS VALID`).

They are **build artefacts, not source**. Rebuild all 21 from the working
database with:

```
cd backend
.venv\Scripts\python.exe tools\build_review_packages.py     # writes review/ + this README
.venv\Scripts\python.exe tools\verify_review_packages.py    # asserts structure and row counts
```

`verify_review_packages.py` re-reads this table, opens every workbook, checks the
`Review` sheet, the exact 10-column header and the real row count, and confirms
that each topic's part numbers are contiguous. It prints `ALL WORKBOOKS VALID`
only when all of that holds.

## Git policy

`.gitignore` lines 70–71 exclude `/review/*.xlsx` and `/review/*.csv`. This
README is the only file under `review/` that git tracks:

```
git ls-files review               -> review/README.md
git ls-files "*.xlsx" "*.csv"     -> (empty)
```

Never commit a workbook: byte-identical content still differs in zip timestamps,
so they would churn on every rebuild and would carry reviewer answers (free text,
possibly personal) into a public repository. Reviewer copies stay on the reviewer's
machine, or move through the import tool, not through git.
