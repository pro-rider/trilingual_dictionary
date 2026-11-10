# Data repair: eight damaged Nepali strings, 2026-11-10

## What was wrong

`backend/tools/check_encoding.py --db backend/data/build/dictionary.sqlite --strict` reported
**2 errors + 9 warnings** over 21 tables and 1,520,169 text cells. Errors were the only strings
carrying U+FFFD; warnings were Devanagari columns containing Latin letters.

Reading each row in context separated three groups:

| Group | Rows | Verdict |
|---|---|---|
| U+FFFD | `senses` 109002, 197466 | damage |
| Latin or Cyrillic typed inside a Devanagari word | `senses` 59001, 66092, 112935, 112963, 170710, `examples` 35 | damage |
| Letters or units that belong there | `senses` 5090 (letter name `C`), `senses` 49650 (`Zhuge Liang`), `examples` 391 (`-20°C`) | legitimate |

`app/translations/script_mix.py` classifies the same rows: only `intra_token_mix` may be
quarantined; `foreign_token` stays visible. The three legitimate rows now live in
`docs/ENCODING-ALLOWLIST.json`, matched on table + column + row + **exact value**, so a row whose
text changes stops matching and cannot hide new corruption. Allowlisting an error is impossible and
a test proves it.

## What was applied

Eight records, evidence per row in `docs/NE-CORRECTIONS.json` (`old` copied byte-for-byte from the
pre-repair database, so the tool can refuse on drift):

| Table | Row | Before | After | Confidence |
|---|---|---|---|---|
| senses | 109002 | `�लनु` | `खन्याउनु` | low, needs_human |
| senses | 197466 | `�त्साहित गर्नु` | `उत्साहित गर्नु` | high |
| senses | 59001 | `शuai उपनाम` | `शुआइ उपनाम` | high |
| senses | 66092 | `केही आश्चर्य नै हoinu` | `केही आश्चर्य नै होइन` | high |
| senses | 112935 | `बatti` | `बत्ती` | high |
| senses | 112963 | `बatti` | `बत्ती` | medium, needs_human |
| senses | 170710 | `दृढतापूर्वक пурсnu` | `दृढतापूर्वक पछ्याउनु` | medium, needs_human |
| examples | 35 | `अनुकरणलाई शब्दसमuhमा …` | `अनुकरणलाई शब्दसमूहमा …` | high |

The high-confidence rows share one property: a single mechanism explains both the damage and the
repair — a string that already exists verbatim in the shipped corpus (`उत्साहित गर्नु` in sense
12575), a transliteration pattern the corpus uses for surnames (`Xiu → शिउ`, `Yuan → युआन`), or a
Latin word sitting exactly where the Devanagari belongs (`batti → बत्ती`, matching `मोमबत्ती`;
`h0inu → होइन`, matching `अचम्म छैन`; `пурсnu → पछ्याउनु`, matching `पछ्याउनु`).

Row 109002 is the exception: the U+FFFD consumed the first syllable, so the original word is not
recoverable. The corpus carries no pouring verb at all (`खन्याउ`/`पोख` returned only `पोखरी`,
"pond"), so `खन्याउनु` comes from the model's knowledge of Nepali and is marked low confidence and
`needs_human`. Three rows in total are a defensible reading rather than a recovery and need a
native reader's confirmation.

## How it was applied

Order matters, and it is enforced by tooling rather than by intention:

1. `backend/tools/preflight.py --intent … --backup …` — git must be clean, pins must match, the
   backup must exist. It returned `STOP (git_clean)` while the tools were still uncommitted, so the
   tooling was committed first and the data change got its own commit, as the pin rule requires.
2. `backend/tools/apply_ne_corrections.py --apply --backup <copy>` — refuses on drift, requires a
   byte-identical backup, updates inside one transaction, demands the affected row count equals the
   pending count, then proves every other `(key, value)` pair unchanged by per-column digest, plus
   per-table row counts, `integrity_check`, `foreign_key_check` and a re-scan for U+FFFD. Re-running
   the same file changes nothing (already-applied rows are counted, not rewritten).
3. `backend/tools/sync_legacy_translation_text.py --apply --backup <copy>` — the same seven sense
   corrections propagated into `translations.db`, which holds an import copy of the legacy Nepali
   and is what `tests/test_resolution.py` compares against. Skip this and two truths exist; the test
   caught exactly that.

## Evidence

| Step | Result |
|---|---|
| dictionary before | `3f9e5f464f18aa75…` (100,765,696 B) |
| dictionary after senses | `0601c3e88ab07b2b…` |
| dictionary after examples | `e1118fb34392b462…` |
| `translations.db` before | `2a6e428467b611f1…` (3,248,128 B) |
| `translations.db` after | `f3b9f3140b72517f…` (3,252,224 B) |
| `assets/data/dictionary.sqlite.gz` rebuilt | `a21809626882867c…` (45,492,153 B), decompresses back to `e1118fb3…` |
| encoding gate, before | 2 errors, 9 warnings |
| encoding gate, now | 0 errors, 0 warnings, 3 allowed |
| backend suite | 269 passed |
| `check_encoding.py --selftest` | `ok=true`, catches both an error and a Devanagari warning |

`translations.db` grew by 4,096 bytes because the replaced text is longer; row count is still 3,245
and no supersession rows were created.

Run-logs: `ne_apply.json`, `ne_apply2.json`, `sync_apply.json`, `preflight_ne2.json`,
`enc_after.json`.

## What remains open

- Three `needs_human` rows need a Nepali reader. `docs/AGENT-NEPALI.md` has the
  `proposed → verified → approved` state machine but no queue surface for a reviewer.
- `fts_zh` still misses entry ids 123597-123672 (76 rows). That is a pre-existing `known_defect`
  recorded in the pin, not something this repair touched; fixing it means an index rebuild.
- `preflight.py` checks git cleanliness but not the *content* of the corrections file against the
  database; the tool's drift check does that, and only when it runs.
- CI cannot see these assets (the database is gitignored, 96 MB), so the asset-level encoding gate
  and the pin check only run locally; CI runs the `--selftest` negative controls instead.
