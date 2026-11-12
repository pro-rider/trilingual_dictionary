# Raw vocabulary ingestion — 2026-11-12

Two spreadsheets the user dropped on the desktop were cleaned and staged. Nothing
was written to `entries` or `senses`, and no English or Nepali text was invented.

## Inputs

| file | rows read | columns | usable | rejected |
|---|---|---|---|---|
| `vocabulary_table.xlsx` (`词表` sheet) | 8,177 | 10 | 8,177 | 0 |
| `vocabulary_table2.xlsx` (`Sheet1`, 27-column grid) | 200 triples + 2,398 `Chinese: …` cells | 27 | 2,598 | 0 |
| combined, after dedupe on headword | — | — | **10,333 unique** | 0 |

`vocabulary_table.xlsx` also carries an author-maintained duplicate log
(`已删除重复`, 24 rows) that was read but not re-applied, since dedupe is done on
the union anyway.

### What the files actually contain

- `vocabulary_table.xlsx`: 8,177 headwords, but only **288 rows** carry pinyin +
  traditional + English + Nepali. The remaining 7,889 are headwords only. The four
  review columns (`你的判定`, `修正后的尼泊尔语`, `备注`) are empty in every row.
- `vocabulary_table2.xlsx`: a 12-column × 200-row grid of technical and literary
  terms, each cell prefixed `Chinese: `, **plus** a separate 200-row table in
  columns Y/Z/AA holding word + pinyin + Chinese explanation. Two cells are the
  same word (星载光谱成像仪 appears at K1 and M1).

## Cleaning applied

1. NFKC normalisation (full-width digits, parentheses, spaces → half-width),
   zero-width and non-breaking space removal, whitespace collapsed then stripped
   from headwords.
2. Duplicate collapse on the simplified headword: 442 duplicate rows merged, and
   the surviving row takes the union of the fields rather than one arbitrary row
   (a bare copy never overwrites a row that has an English gloss).
3. Rejection rule is *Chinese-character presence*, not script purity. `X射线`,
   `记忆B细胞`, `蛋白激酶B活化` are legitimate headwords; rejecting them as
   "Latin mixed" would have deleted real vocabulary. Rules that did fire: empty
   cell, no Han character, symbols only, U+FFFD/mojibake, headword over 20 chars.
   0 rows were rejected under those rules.
4. Pinyin was generated for every accepted row with `pypinyin`
   (`TONE` → `pinyin`, `TONE3` → numbered, `NORMAL` → plain, plus a
   spaced+nospaced `search` field), and the supplied pinyin was used as the marked
   form when the file had one. The four-field quartet is written to the audit JSONL
   because the staging table stores a single `pinyin` column; `entries` receives the
   full quartet at promotion time.
5. `char_count` = `LENGTH(word)`; verified 0 mismatches.

## Landing place

`words3000_candidates` only, tag `source = user-raw-2026-11-12`.

| status | rows |
|---|---|
| `pending_gloss` (headword only) | 6,798 |
| `glossed` (English and/or Nepali, no Chinese) | 118 |
| `glossed_zh_only` (Chinese explanation, no English/Nepali) | 88 |
| already in the dictionary (skipped, logged) | 3,323 |
| already staged earlier (skipped) | 6 |
| upgraded from `pending_gloss` | 0 |
| rejected | 0 |

Table total: 1,348 → **8,352 rows**
(`pending_gloss` 7,089, `glossed` 438, `glossed_ai` 737, `glossed_zh_only` 88).

Note: `glossed` is the staging table's own pre-existing value for "has a real
translation but no Chinese gloss"; the brief's three statuses assume
Chinese-only input, and forcing 118 already-translated rows down to
`pending_gloss` would have thrown away real content.

## Conflicts with the existing database

3,323 of the 10,333 headwords already exist in `entries`, so they were not
staged. Inside that group **44 rows carry a Chinese explanation that the shipped
sense does not have** — a real, small win that needs a targeted import (map the
gloss onto the matching sense), not a staging row.

## Side effects on the release record

Staging changed the working DB (121,700,352 → 122,544,128 B,
`sha256=23ad3b7b9c20…`). A fresh release build from it produced **byte-different
but content-identical** tables — every table digest matched
(`tools/compare_release_content.py` → CONTENT IDENTICAL) because the release build
drops `words3000_candidates`. The approved shipped asset `db-8b0db9597b` was
therefore **not** rebuilt; the release DB file was restored from the approved
packed asset, and only the working-copy pin moved, with the reason written into
`docs/ASSET-PINS.json`. Approval state remains APPROVED.

## Artifacts

- `backend/tools/ingest_user_vocab.py` — dry-run by default switch `--dry-run`, idempotent re-run
- `backend/tools/validate_ingest.py` — proof that `entries`/`senses`/`examples` are untouched
- `backend/tools/compare_release_content.py` — content-level equality between a fresh build and the shipped asset
- `backend/tools/repin_after_staging.py` — pin move that refuses to run if the asset stops verifying
- `docs/ingest_user_vocab_20261112T112657Z.jsonl` — one line per inserted row with its full pinyin quartet
