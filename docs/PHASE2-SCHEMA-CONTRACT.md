# Phase 2 — schema contract (v3), governance decisions and freeze checklist

Status: **implemented, not frozen** — waiting for your approval. Phase 3 and all
large-scale translation have not started; no existing data was deleted, rewritten
or hidden.

Store: `backend/data/build/translations.db` (schema **3**, its own file, never
inside `dictionary.sqlite`).

> **Phase 2.1 delta (this revision).** Read `docs/PHASE2.1-CORRECTIONS.md` for
> the full correction record. In short:
> * the 3,245 legacy Nepali values are now imported into this store (batch
>   `legacy-ne-20261109T085958Z`), verified value-by-value, reversible with
>   `--rollback-batch`; `dictionary.sqlite` stays the authoritative original and
>   was never written to;
> * schema 3 adds `sense_match_method`, `evidence_language`, `import_batch`,
>   `evidence.language`, the `translations_by_import_batch` index and the
>   `verification_authority_role_is_human` trigger;
> * “Source-supported” now requires direct **lexical Nepali** evidence with a
>   **defensible sense match** (`sense_gloss`/`sense_id`/`qid`/`article`), not a
>   source URL (golden vectors grew from 12 to 17);
> * backup/restore verification is content-level (`content_fingerprint`), not
>   row counts or file hashes;
> * counts are reconciled with units and queries in `docs/PHASE2.1-COUNTS.md`;
> * the `fts_zh` trigram index is 76 entries short (ids 123,597–123,672, including
>   `一天`/`一年`) — latent today because no code path queries FTS, fixed at the
>   next build via `tools/rebuild_fts.py`.

---

## 1. Why schema 1 was replaced

Schema 1 had one `status` column carrying five unrelated facts at once, and its
`verified`/`reviewed` names implied human verification purely from a label. Both
are dishonest at read time. Schema 2 stores dimensions and derives labels.

| schema 1 | schema 2 |
|---|---|
| `status` (`verified/reviewed/ai_checked/ai_unverified/quarantined`) | kept verbatim as `legacy_status` + five dimension columns |
| `source_type` (`human/dict/ai/import`) | `generation_method` + `origin_method` |
| `evidence_category` (A–D) | kept, plus derived `evidence_strength` (`direct/strong/weak/none`) |
| reviewer required for `verified` | `human_verification` + `verification_authority_id`, protected by triggers |

## 2. Field definitions (`translations`)

| field | type | meaning / allowed values |
|---|---|---|
| `translation_id` | int PK | stable identity of the row |
| `sense_key` | text | `simplified ␟ pinyin ␟ gloss_en`, normalized (`\x1f` separator) |
| `entry_key` | text | `simplified ␟ pinyin` |
| `language` | text | `ne` / `zh` / `en` |
| `text` | text | the translation value; never rewritten in place |
| `legacy_status` | text|null | the v1 status, verbatim, for audit only |
| `generation_method` | text | `source_import` / `llm` / `rule_based` / `legacy_unknown` |
| `evidence_strength` | text | `direct` (Category A lexical) / `strong` (B/C) / `weak` (D) / `none` |
| `validation_status` | text | `passed` / `failed` / `incomplete` — **format and rule checks only** |
| `publication_status` | text | `published` / `labeled` / `quarantined` |
| `human_verification` | text | `not_verified` / `verified` — only an authorised human workflow may set `verified` |
| `verification_authority_id` | int FK | must reference an `authorized=1` row in `verification_authorities` |
| `origin_source` | text | e.g. `wiktionary`, `tatoeba`, reviewer name |
| `origin_source_url` | text | URL of the record |
| `origin_source_version` | text | dataset/dump version |
| `origin_record_id` | text | id inside that source |
| `origin_retrieved_at` | text | ISO-8601 UTC retrieval time |
| `origin_method` | text | how the value entered (`llm`, `source_import`, `human`, …) |
| `sense_match_confidence` | real 0–1 | how sure the mapping to *this sense* is |
| `evidence_ids` | text | JSON list of `evidence.evidence_id` |
| `evidence_category` | text | `A/B/C/D`, the evidence class the row rests on |
| `model_version`, `prompt_version`, `source_data_version`, `validator_version` | text | reproduction inputs |
| `confidence` | real | model self-reported confidence (**not** accuracy) |
| `flags` | text | JSON list of validator flags |
| `reviewer`, `reviewed_at`, `reviewer_note` | text | human review record |
| `quarantine_reason`, `quarantine_rule`, `quarantine_batch`, `quarantined_at` | text | why and by which rule; required when `quarantined` |
| `supersedes_id` | int FK | corrections point at the row they replace |
| `created_at`, `updated_at` | text | ISO-8601 UTC |

Governance tables: `verification_authorities`, `sense_pos`, `sense_hsk`,
`entry_aliases`, `sense_aliases`, `id_collisions`, `quarantine_records`,
`user_corrections`, `event_log` (plus the unchanged `evidence`, `versions`,
`id_map`).

### Hard rules encoded in the database, not in callers

1. `translations_verification_requires_authority` — an INSERT may set
   `human_verification='verified'` only if it names an authority row with
   `authorized = 1`. The translation pipeline has no such row, so **the pipeline
   cannot mark its own output verified**.
2. `translations_verified_requires_reviewer` — a verified row needs `reviewer`.
3. `translations_verified_immutable_update` / `…_delete` — a verified row cannot
   be edited or deleted at all; a correction is a new row with `supersedes_id`.
4. `translations_verification_is_append_only` — `human_verification` can never be
   changed by an UPDATE, in either direction. Promotion and downgrade both require
   a new row, which leaves the original in place.
5. `translations_quarantine_needs_reason` — closing `quarantined` without a
   reason is refused.
6. `quarantine_record_needs_text` — a quarantine record must carry the original
   value, so `quarantine_records.original_text` is the restore path.
7. `QUARANTINE` is reversible by design: `publication_status` may be moved back,
   and `quarantine_records.restored_at/restored_by` record who undid it.

Limitation stated plainly: triggers defend against every write path that goes
through SQLite with triggers enabled. They are **not** protection against
someone editing the `.db` file directly with an external tool.

## 3. Legacy status → dimensions mapping (implemented)

| legacy_status | generation_method | evidence_strength | validation_status | publication_status | human_verification |
|---|---|---|---|---|---|
| `verified` | `legacy_unknown` | `none` | `incomplete` | `labeled` | `not_verified` |
| `reviewed` | `legacy_unknown` | `none` | `incomplete` | `labeled` | `not_verified` |
| `ai_checked` | `llm` | `weak` | `passed` | `labeled` | `not_verified` |
| `ai_unverified` | `llm` | `none` | `incomplete` | `labeled` | `not_verified` |
| `quarantined` | `legacy_unknown` | `none` | `failed` | `quarantined` | `not_verified` |

Then, only when the legacy `evidence_category` actually held A–D, the strength is
refined to `A→direct`, `B/C→strong`, `D→weak`, and a `legacy_unknown` row whose
evidence was A–D becomes `generation_method='source_import'` (evidence implies a
source existed, a status name does not).

`source_type` is carried into `origin_method` (`ai→llm`, `dict/import→source_import`,
`human→human`). No legacy row ever lands on `verified`; every migrated row writes
an `event_log` entry `map_legacy_status` with the note “legacy status name is not
evidence of human verification”. Legacy `quarantined` rows also get a
`quarantine_records` row holding their original text and an explicit
reason string (“reason not recorded”), because schema 1 stored none.

## 4. UI label derivation (one function, three consumers)

Implemented in `backend/app/translations/status.py` and mirrored in
`lib/core/translation_status.dart`; both are tested against the same vectors in
`shared/translation_status_golden.json` (12 cases, all passing on both sides).

Ladder — first match wins:

| # | condition | code | label | visible |
|---|---|---|---|---|
| 1 | `publication_status = quarantined` | `quarantined` | Hidden from results | no |
| 2 | `human_verification = verified` | `verified` | Verified | yes |
| 3 | `validation_status = failed` | `flagged` | Flagged — failed checks | yes |
| 4 | `evidence_strength = direct` ∧ `passed` ∧ `origin_source` set | `source_supported` | Source-supported · \<source\> | yes |
| 5 | `generation_method = llm` ∧ evidence direct/strong ∧ `passed` | `ai_checked` | AI-translated, checked | yes |
| 6 | `generation_method = llm` | `ai_unverified` | AI-translated, unverified | yes |
| 7 | `generation_method = source_import` ∧ evidence direct/strong ∧ `passed` | `source_sense_unconfirmed` | Source-recorded, sense unconfirmed | yes |
| 8 | `generation_method = legacy_unknown` ∨ `validation_status = incomplete` | `unverified_legacy` | Unverified — source unknown | yes |
| 9 | anything else | `source_sense_unconfirmed` | Source-recorded, sense unconfirmed | yes |

Worked examples from the golden file:

* legacy `reviewed` row (all new fields defaulted) → `Unverified — source unknown`.
  An old status name cannot produce “Verified”.
* `llm` + `strong` evidence + `passed` → `AI-translated, checked`.
* `llm` + `passed` but `evidence_strength = none` → `AI-translated, unverified`:
  passing format checks without evidence does not upgrade the label.
* `direct` evidence + `passed` but no `origin_source` → `Source-recorded, sense
  unconfirmed`, **not** `Source-supported`.
* `verified` row that later fails validation still reads `Verified` (verification
  outranks checks) but rule 1 still hides it if it is quarantined.

`visible=false` is the only contract the UI needs for hiding quarantined values;
the label string is presentation, never stored.

## 5. Provenance audit categories and the counts established from the store

Measured read-only against `dictionary.sqlite` (mode=ro), all 3,245 Nepali senses:

| category | count | evidence |
|---|---|---|
| `automatically_generated` | **3,245** | every row has `senses.ne_status = 'ai_translated'` |
| `unknown_provenance` | **0** | no row lacks a `ne_status` |
| `known_source_strong_sense` | **0** | no `origin_source_url` / `origin_record_id` anywhere; `senses.source_id` is the constant `1` for 3,169 rows and null for 76 — an internal bucket id, not a source |
| `known_source_uncertain_sense` | **0** | — |
| `human_verified` | **0** | `senses_ne_reviewed = 0`; nothing records a reviewer |

So the honest picture: the existing Nepali is **machine-generated by an
unidentified model/run**, with no source, no model version and no reviewer
retained. It is not “unknown origin”; it is “AI origin, provenance lost”. Its
script is valid (3,230 rows Devanagari-only) but that proves nothing about
meaning. Nothing is hidden or deleted because of that.

`dictionary.sqlite` has no provenance column to recover a model or prompt
version from; `ai_cache` holds a single row, so the original run is not
reconstructible. That is recorded here rather than papered over.

## 6. Existing Nepali values: preservation guarantee

* Not one of the 3,245 values is deleted, blanked or replaced in Phase 2.
* The only rows that may be quarantined are the 7 with Latin letters mixed into
  Devanagari (`बatti`, `शuai उपनाम`, `पурсnu`, `केही आश्यर्य नै हoinu`,
  `सूची अक्षर C`, `Zhuge Liang को सम्मान नाम`, plus one more from the audit),
  and even those keep their text in `quarantine_records.original_text` with a
  reason and a rule id. They are not marked wrong in the dictionary.
* Unknown provenance never triggers quarantine. Legacy AI values stay visible
  with the `Unverified — source unknown` / `AI-translated, unverified` label.
* No AI value will ever silently replace a legacy value: corrections are new
  rows, `supersedes_id` links them, and the old row remains readable.

## 7. POS decision

* `senses.pos_primary` is preserved untouched; it is **not** treated as
  CC-CEDICT metadata. CC-CEDICT glosses carry no POS field, so a POS parsed from
  an English gloss is our inference, not the source's data.
* New storage: `sense_pos(pos_id, sense_key, pos, pos_source, pos_source_type,
  confidence, matched_by, created_at)`. A sense may hold several POS values,
  each with its own source and confidence.
* `pos_source_type` distinguishes `source_confirmed` (the source itself states
  the POS), `predicted` (heuristic from gloss/struct), `unknown`.
* `matched_by` records whether the match came from headword, headword+pinyin,
  sense+gloss or a heuristic. Headword-only matching is recorded as such so its
  weaker reliability is visible — and it is not used when a headword has several
  senses.
* No POS is assigned when evidence is insufficient; `POS` coverage will be
  reported with an explicit “unmatched” count rather than filled in silently.

Unresolved: which documented, licensed POS source to use. Candidates to
evaluate in Phase 1.5: the CC-CEDICT `CL:` classifier markers (measure words
only, and they *are* source-confirmed), Wikidata `instance of`/`subclass of`
(weak and patchy for POS), and a licensed Chinese POS lexicon. My
recommendation: start with what CC-CEDICT actually states (classifiers, `surname`,
`variant of`, `abbr. for`), mark everything else `predicted`, and accept low
coverage.

## 8. HSK decision

Storage: `sense_hsk(hsk_id, entry_key, sense_key, hsk_standard, hsk_level,
hsk_source, hsk_version, confidence, created_at)`. `hsk_standard` and
`hsk_level` are separate columns precisely so a 3.0 level can never be read as a
2.0 level; no cross-standard conversion is implemented or implied.

Existing values are preserved as-is: 2,477 entries with `hsk_level = 5`, and
that is the **only** level present.

What the overlap investigation found (read-only, this round):

| measurement | value |
|---|---|
| entries with any HSK level | 2,477 |
| entries with ≥1 Nepali sense | 2,968 |
| HSK entries that also have Nepali | **2,477 (100%)** |
| Nepali senses inside HSK entries | **2,737 of 3,245 (84.3%)** |
| senses inside HSK entries (all) | 7,447 |
| Nepali coverage inside the HSK batch | 2,737 / 7,447 = **36.8%** |

So the two datasets are **not independent at all**: every HSK-tagged entry is
already Nepali-tagged, and 84% of all Nepali sits inside them. Consequences:

* “HSK 1–6” cannot be used as a coverage gate today — there is no level other
  than 5.
* The 2,477-entry HSK-5 batch is the natural, already-partly-translated pilot
  population for Phase 3 (36.8% covered → 4,710 senses still empty there).
* Any HSK re-import must be keyed by `entry_key`/`sense_key` and must not
  overwrite the existing `entries.hsk_level` values until a documented standard
  replaces them.

Unresolved (needs your decision before Phase 1.5 §6): HSK 2.0 or 3.0, the exact
dataset URL, its version/retrieval date, license and attribution text, whether
simplified/traditional variants are included, and whether it carries trustworthy
POS. I will not backfill until those are written down here.

## 9. Freeze checklist (schema 2 vs what remains undecided)

| requirement | state |
|---|---|
| Immutable entry/sense ids | `id_map(sense_id, data_version)` + `entry_key`/`sense_key`; id build is Phase 1.5 |
| Alias / redirect tables | `entry_aliases`, `sense_aliases` created; population is Phase 1.5 |
| ID collision reporting | `id_collisions` created (`kind`, `key`, `members_json`, `resolution`) |
| Event log | `event_log` created and already used by the v1→v2 migration |
| Dimension fields | done (§2) |
| Provenance fields | done (`origin_*`, `sense_match_confidence`, `evidence_ids`) |
| POS structure | done (§7); source choice open |
| HSK structure | done (§8); standard/source open |
| Quarantine metadata + restore | done (`quarantine_*` + `quarantine_records.original_text`) |
| User corrections separated | `user_corrections` created, distinct from pipeline rows |
| Migration + rollback | §10, tested |
| Indexes/constraints | 10 indexes, CHECK constraints on every dimension |
| UI derivation contract | §4, golden-vector tested on both sides |

Not frozen yet, deliberately: nothing here depends on a structure that Phase 1.5
must change. The two genuinely undecided inputs (POS source, HSK standard/URL)
are left blank in this contract rather than pre-filled with a guess.

## 10. Migration and rollback

`python backend/tools/migrate_translations.py [--dry-run] [--data-version V] [--rollback BAK]`

* v1→v2 rebuilds `translations` (SQLite's documented table-rebuild procedure:
  `foreign_keys=off`, rename, create, copy, drop, recreate indexes/triggers),
  keeps `translation_id` values, and verifies with `pragma foreign_key_check`
  (`foreign_key_violations = 0` on the real store).
* Backup uses the SQLite backup API before any change; a backup is compared by
  content (`schema.snapshot()`: version + tables + row counts), never by file hash
  — SQLite may rewrite page layout.
* Rollback refuses a backup outside the database directory, moves the current
  file aside as `*.rollback-<stamp>`, removes stale `-wal`/`-shm`, restores, and
  returns the resulting snapshot.
* A store at a higher schema version is refused loudly (“refusing to touch it”),
  not silently treated as up to date.
* Applied for real: `data/build/translations.db` 1 → 2, backup
  `translations.db.bak-20261109T084617Z`, before/after row counts identical (0
  translations in both), 14 tables, 7 triggers, FK violations 0, `versions` now
  holds `schema=1`, `dictionary=2026-11-09.3`, `schema=2`.

## 11. Tests

| suite | file | result |
|---|---|---|
| schema v2 + triggers + migration | `backend/tests/test_translations_schema.py` | 11 passed |
| derivation golden vectors (Python) | `backend/tests/test_translation_status.py` | 16 passed |
| derivation golden vectors (Dart) | `test/translation_status_test.dart` | 4 passed, `flutter analyze` clean |
| backend whole suite | `backend/tests` | 91 passed |

Covered explicitly: pipeline cannot insert `verified`; authorised verification is
accepted and then immutable (update and delete both refused); `human_verification`
cannot be flipped by UPDATE; quarantine needs a reason; quarantine records keep
the original text; unknown schema version fails loudly; rollback restores content;
dry-run writes nothing; `sense_key` is stable across whitespace and case.

## 12. Known limitations / open questions

1. FTS5 trigram index must be rebuilt whenever `dictionary.sqlite` is rebuilt —
   **not automated yet**; tracked as a launch gate.
2. POS source not chosen (§7) and HSK standard/URL not chosen (§8) — both block
   their backfills in Phase 1.5.
3. The 40 Nepali values shared across different glosses are still unclassified;
   classification is Phase 1.5 §4.
4. Provenance of the legacy AI run is unrecoverable (no model id, no prompt
   version, single `ai_cache` row).
5. Triggers cannot stop an external tool editing the file, only SQL paths.
6. The real store holds 0 translations, so the v1→v2 mapping is exercised by
   synthetic fixtures in tests rather than by production data; the mapping table
   is nevertheless implemented and asserted row-by-row.
