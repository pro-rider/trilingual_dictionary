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
