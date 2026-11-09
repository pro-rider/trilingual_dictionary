# Phase 2.1 — schema corrections before freeze

Scope: fix the three critical issues and answer the nine data-ownership
questions. **No Phase 1.5 audit has been run, no Phase 3 translation started,
`dictionary.sqlite` was never written to.** Everything below is reproducible
from the commands shown.

Store: `backend/data/build/translations.db`, schema **3**.
Source of truth: `backend/data/build/dictionary.sqlite`, opened `mode=ro` by
every tool in this phase.

---

## 1. Data ownership and mapping contract

**Who owns what**

| data | owner | mutable by us | read path |
|---|---|---|---|
| Original Chinese headword, pinyin, English gloss, examples, images, HSK/POS columns | `dictionary.sqlite` | no (build pipeline only) | direct |
| Original Nepali value `senses.gloss_ne` + `ne_status` | `dictionary.sqlite` | **no** — authoritative original | direct |
| Governance state: labels' inputs, batch, quarantine, corrections, human verification | `translations.db` | yes, append-only for verified rows | overlay on the sense |

**The nine questions**

1. **Is `senses.gloss_ne` the authoritative original?** Yes. It is what shipped,
   and it is never rewritten by anything in this phase. Every imported row keeps
   `origin_record_id = sense_id` so it can be traced back byte for byte.
2. **Do the existing translations stay there permanently?** Yes. Nothing is
   removed from the dictionary; the import is a copy, not a move.
3. **Are they also imported into `translations.db`?** **Yes, now.** All 3,245
   values are imported (see §2), tagged with a batch id, so governance can act on
   them without touching the protected original.
4. **How do their ids map to the original sense ids?**
   `translations.origin_record_id` holds the dictionary `sense_id`, and
   `id_map(entry_id, entry_key, sense_id, sense_key, data_version)` holds the
   full mapping including the stable keys. 3,245 `id_map` rows exist.
5. **How are duplicate translations prevented?** The importer refuses a row that
   already exists with the same `(sense_key, origin_source, origin_record_id)`;
   re-running a batch reports `inserted 0 / duplicates_skipped 3,245` (tested).
   Two *different* source records that happen to carry the same Nepali text are
   kept, because they are different senses and the label is per sense.
6. **How does the app read both legacy and new translations?** One order:
   dictionary value first (it is the original), then the governance row for
   that `sense_key` decides the badge and whether a newer value supersedes it.
   A quarantined row hides the value; a `supersedes_id` chain means "show the
   newest non-quarantined row, keep the original readable".
7. **How does the app avoid showing the same Nepali meaning twice?** It renders
   **one** Nepali line per sense, chosen by: newest non-quarantined row for that
   `sense_key`, falling back to the dictionary value. Because the key is
   `simplified ␟ pinyin ␟ gloss_en`, two senses of the same headword are separate
   lines by design (that is the 40-shared-value case, not a duplicate).
8. **How do corrections and quarantine work without touching the dictionary?**
   They are rows in `translations.db`: a correction is a new row with
   `supersedes_id`; a quarantine sets `publication_status='quarantined'` plus
   reason/rule/batch/time and writes `quarantine_records` with the original text,
   so it can be restored without any dictionary write.
9. **What is the rollback strategy for this import?**
   `import_batch` on every row + `--rollback-batch <id>`, which deletes exactly
   those rows, logs the removal in `event_log`, and leaves the dictionary
   untouched (tested: fingerprint of the dictionary is identical before and
   after an import + rollback).

**Reading contract for Phase 3 and the app (written down so it cannot drift):**
`translations.db` never becomes the only place a Nepali value lives. The
dictionary keeps the value it shipped; the store adds governance and, later,
better values that explicitly supersede it.

## 2. The import, executed and verified

```
python backend/tools/migrate_translations.py            # 2 -> 3, backs up first
python backend/tools/import_legacy_ne.py                # dry run, writes nothing
python backend/tools/import_legacy_ne.py --apply        # writes, tags a batch
python backend/tools/import_legacy_ne.py --verify       # value-by-value check
python backend/tools/import_legacy_ne.py --rollback-batch legacy-ne-<stamp>
```

Result on the real data:

| check | value |
|---|---|
| dictionary senses with a Nepali value | 3,245 |
| rows planned by the importer | 3,245 |
| rows rejected (key components missing) | 0 |
| rows inserted | 3,245 (`duplicates_skipped 0`) |
| imported rows re-checked against the dictionary | 3,245 |
| text mismatches | **0** |
| key mismatches (`sense_key`/`entry_key`) | **0** |
| sense ids not found in the dictionary | 0 |
| dictionary rows missing from the store | 0 |
| `id_map` rows | 3,245 |
| foreign key violations / `quick_check` | 0 / ok |
| batch | `legacy-ne-20261109T085958Z` |

The first verification run reported 3,245 text mismatches — my check had read
`gloss_en` where it meant `gloss_ne`. That is fixed and the re-run is 0
mismatches; it is recorded here because a silent version of that bug is exactly
how a wrong import would ship.

## 3. What `ne_status = 'ai_translated'` actually guarantees

Established from the code and docs, not inferred:

* The value was written by `tools/enrich_dictionary.py` (see
  `DATA-GOVERNANCE.md` §14: “`ne_status` is set to `ai_translated` (never
  `reviewed`), so machine output stays distinguishable from reviewed entries”).
* `ne_status` has exactly two values in the store: `none` (195,061) and
  `ai_translated` (3,245). There is no third, human-originated value.
* The only surviving run report (`dictionary.sqlite.enrich.report.json`) holds
  `total/done/ne/examples/elapsed_s` — **no model name, no prompt, no provider**.

Therefore:

| claim | established? |
|---|---|
| Generated by a machine (a model, not a person) | **yes**, by builder semantics |
| Which model | no |
| Which prompt | no |
| Whether technical validation ran | no |
| Whether a human reviewed it | **no — and the marker explicitly excludes it** |
| Semantically correct | **no** — unrelated to this flag |

So the import maps `generation_method='llm'` and sets `evidence_strength='none'`,
`validation_status='incomplete'`, `human_verification='not_verified'`,
`evidence_language=null`, `sense_match_method=null`, `model_version=null`,
`prompt_version=null`, while keeping `legacy_status` (null for these rows, they
never had one) and writing `origin_method='legacy_ai_import'`,
`origin_source='dictionary.sqlite:senses.ne'`,
`origin_source_version='dictionary-2@2026-11-08T00:06:54'`, and the original
`sense_id`. The label that results is `AI-translated, unverified` — correct for
what is actually known.

## 4. Backup and restoration verification is now content-level

`schema.content_fingerprint(path)` hashes **every row of every table**, in
primary-key order, with `\x1e` between fields and `\x1d` between rows, and
returns per-table `{rows, sha256}` plus a combined `content_sha256` and a
`quick_check` result.

* `rollback()` now returns `content_matches_backup`, the restored
  `content_sha256`, and `integrity`; the test asserts the restored store equals
  the backup's fingerprint, not its file bytes.
* Raw file hashes remain deliberately unused as a verification signal — SQLite
  backups and WAL can differ physically while being logically identical.
* Tests: identical content in two different files ⇒ identical fingerprint;
  one changed value at identical row count ⇒ different fingerprint (this is the
  exact case row counts miss); rollback ⇒ `content_matches_backup = True`.

## 5. “Source-supported” is now a narrow claim

Rule 4 in the derivation ladder requires **all** of:

1. `evidence_strength = 'direct'` (Category A lexical evidence),
2. `evidence_language = 'ne'` (English/Chinese evidence cannot back a Nepali value),
3. `sense_match_method ∈ {sense_gloss, sense_id, qid, article}` — headword-only
   or heuristic matching does **not** qualify,
4. `origin_source` named (attribution exists),
5. `validation_status = 'passed'` (technical checks only),
6. `publication_status ≠ quarantined` and `human_verification ≠ verified` handled
   earlier in the ladder.

Schema 3 adds `evidence_language` and `sense_match_method` columns to make 2 and
3 storable and testable, and `evidence.language` for the evidence table.

Golden vectors cover the negative cases: source URL alone → *Source-recorded,
sense unconfirmed*; English-language evidence → same; `headword` match → same;
`heuristic` match → same. Attribution and sense-match confidence stay separate
fields, never merged into one score.

## 6. Human-verification authorization

* `verification_authorities(name, role, authorized, created_at, note)` plus a
  trigger: `role` must be `reviewer` or `admin`. A row with `role='pipeline'` is
  refused outright (tested) — the translation pipeline cannot create an
  authority for itself.
* An INSERT may set `human_verification='verified'` only with
  `verification_authority_id` pointing at an `authorized=1` authority and a
  non-empty `reviewer`.
* `human_verification` cannot be changed by any UPDATE (promotion *and* downgrade
  refused), and a verified row cannot be updated or deleted at all. Corrections
  therefore go through a new row with `supersedes_id`, leaving both rows auditable.
* Tests: unauthorised insert refused; authorised insert accepted then immutable
  under update and delete; append-only flip refused; missing reviewer refused;
  legacy `reviewed`/`verified`/`ai_checked` never produce a verification claim.

## 7. Count units, reconciled

Full table with queries: `docs/PHASE2.1-COUNTS.md`. The contested numbers:

| number | unit | query |
|---|---|---|
| 123,672 | entry | `select count(*) from entries` |
| 198,306 | sense | `select count(*) from senses` |
| 3,245 | sense carrying a Nepali value | `... where trim(gloss_ne)<>''` |
| 2,968 | entry with ≥1 Nepali sense | `count(distinct s.entry_id)` |
| 2,477 | entry with `hsk_level` not null (all = 5) | `... where hsk_level is not null` |
| 7,447 | sense belonging to those entries | join on `entry_id` |
| 2,737 | sense with Nepali inside those entries | join + `gloss_ne<>''` |
| 3,245 | translation record in `translations.db` | `select count(*) from translations` |

Overlap uses `entry_id` (dictionary) and `entry_key` (derived), never a headword
string match, so both sides use the same identity rule.

## 8. Search index (FTS5) — ownership, invalidation, and a real defect found

Search is served from **two FTS5 virtual tables inside `dictionary.sqlite`**:

| table | columns | tokenizer | rows | entries |
|---|---|---|---|---|
| `fts` | simplified, traditional, pinyin_search, english, category, entry_id | unicode61 | 123,672 | 123,672 ✔ |
| `fts_zh` | simplified, traditional, english, entry_id | trigram | **123,596** | 123,672 ✘ |

**Defect:** `fts_zh` is missing the **76 newest entries** (`entry_id`
123,597–123,672). They include high-frequency headwords: `一天` (freq 728),
`一年` (874), `两年`, `两天`, `三天`, `那年`, `流走`, `五级`, `闻闻`, `牢牢地`.
A trigram query for `一天` cannot hit that index. `fts` is complete, which is why
the gap went unnoticed.

**Who uses it:** neither the Flutter app nor `backend/app/services/sqlite_dataset.py`
queries FTS today — `find_entry` uses exact / prefix / pinyin / gloss SQL and
the app uses its own queries. So the defect is latent, not user-visible right
now, and it becomes visible the moment FTS is wired into ranking (G4).

**Invalidation:** any rebuild or data change of `entries`. `build_dictionary.py`
creates both tables; `r5_import.py` appends to both — the 76-row gap means the
last import batch did not reach `fts_zh`, which is a build-side bug to fix,
not something to patch into a shipped asset.

**Rebuild and verify tool** (`backend/tools/rebuild_fts.py`, verify-only by default,
read-only connection):

```
python backend/tools/rebuild_fts.py                 # verify: row counts + sample hit + quick_check
python backend/tools/rebuild_fts.py --db <copy> --rebuild
```

Rebuild is `delete-all` + re-insert from `entries`, so it is reproducible from
the base table alone and never derives data. It must run in the build step
(after `r5_import.py`), then the asset is re-bundled — the source
`dictionary.sqlite` is not patched in place.

## 9. Migration and rollback tests added in 2.1

| test | asserts |
|---|---|
| `test_content_fingerprint_separates_equal_counts_from_equal_content` | same row count, different value ⇒ different fingerprint |
| `test_content_fingerprint_is_stable_for_identical_content` | equal content ⇒ equal fingerprint across files |
| `test_rollback_reports_content_match` | `content_matches_backup`, restored hash = backup hash, integrity ok |
| `test_verification_authority_must_be_a_human_role` | `role='pipeline'` refused; reviewer accepted |
| `test_import_maps_real_dictionary_shape_and_rolls_back` | 3 rows planned, imported, verified, id_map 3, dictionary fingerprint unchanged, batch rollback deletes exactly 3 |
| `test_import_is_idempotent` | second apply ⇒ `inserted 0`, `duplicates_skipped 3` |
| `test_quarantine_is_reversible_and_keeps_the_value` | text preserved, `restored_at`/`restored_by` recorded, row can leave quarantine |
| schema 3 upgrade | 2 → 3 adds the columns without touching rows; backup taken first |

Backend suite: **103 passed** (11 schema, 16 derivation, 8 Phase 2.1, plus the
existing 68). Dart: 4 passed, `flutter analyze` clean.

## 10. Remaining unresolved decisions

1. HSK standard/URL/licence — still open, still blocks the HSK backfill.
2. POS source — recommendation stands: only what CC-CEDICT itself states
   (`CL:` classifiers, `surname`, `variant of`, `abbr. for`) as
   `source_confirmed`; everything else `predicted`; low coverage accepted.
3. Whether the 7 mixed-script values get quarantined in Phase 1.5 (reversible
   either way; originals already recoverable).
4. The 40 shared-Nepali cases remain unclassified (Phase 1.5 §4).
5. The `fts_zh` 76-row gap is fixed only after the next dictionary build; until
   then FTS must not be used for ranking.
6. The importer maps `generation_method='llm'`; if you want `legacy_unknown`
   instead, that is a one-line change and a re-import — but the evidence supports
   `llm`.
