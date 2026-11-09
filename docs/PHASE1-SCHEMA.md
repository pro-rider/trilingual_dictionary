# Phase 1 — schema specification and audit result

Deliverables of this phase: a read-only audit (`docs/PHASE1-AUDIT.md`), this
schema specification, and a tested migration that creates the store, backs up
before any change and can roll back. No agent code exists yet.

## Where the data lives, and why

`backend/data/build/translations.db` — a new file, never the shipped
`dictionary.sqlite`.

The dictionary file is replaced whenever `assetVersion` changes (that is what
`OfflineDictionary._openInner()` does), and reviewed translations must survive
that. Keeping them apart also means the dictionary file stays exactly what the
build produced: read-only, reproducible, hash-comparable. A delta pack built from
`translations.db` is a patch over stable keys, not an edit of the dictionary.

## Stable identity

Row ids (`entry_id`, `sense_id`) are rebuilt on every dictionary build and are
therefore forbidden as foreign keys of content.

```
entry_key = normalized(simplified) \x1f normalized(pinyin_plain)
sense_key = entry_key \x1f normalized(gloss_en)
normalized(x) = collapse whitespace, trim, lowercase
```

`id_map(sense_id, data_version) → (entry_id, entry_key, sense_id, sense_key)`
records what the current build's ids mean, so a build can be diffed against the
previous one and a vanished `sense_id` is detectable rather than silently
re-pointed. `sense_key` matches the key the Flutter app already uses for
`user.db`, so the app and the server agree without a translation layer.

Known limit: two senses of one entry that differ only by punctuation or case in
the English gloss would collide. The unique index on
`(sense_key, language, text)` would then reject a legitimate duplicate; the
import job must detect the collision and fall back to including `sense_order`.

## Tables

| Table | Purpose |
|---|---|
| `translations` | one row per proposed or accepted value, with status, provenance, validator flags, supersession |
| `evidence` | one row per retrieved evidence item, with `category` A–D |
| `versions` | which schema / dictionary / prompt / model / termbase version produced what |
| `id_map` | row ids of the current dictionary build mapped to stable keys |

`translations` columns: `translation_id, sense_key, entry_key, language, text,
status, source_type, evidence_ids, evidence_category, model_version,
prompt_version, source_data_version, confidence, flags, reviewer, reviewed_at,
reviewer_note, supersedes_id, created_at`.

Statuses and what each one promises:

| Status | Means | Who may create it |
|---|---|---|
| `verified` | checked by a Nepali-literate reviewer, immutable | reviewer only (requires `reviewer`) |
| `reviewed` | human-approved wording, immutable | reviewer only (requires `reviewer`) |
| `ai_checked` | passed automatic gates and a human sample, **still not verified** | automation, after the Phase 10 gates |
| `ai_unverified` | model output, no human judgment | agent |
| `quarantined` | rejected by a gate, with the reason in `flags` | agent or reviewer |

Evidence categories (`evidence.category`):
`A` direct lexical translation (Wiktionary/Kaikki `ne`), `B` contextual sentence
(Tatoeba), `C` conceptual/entity (Wikidata label, Wikipedia link), `D` weak
indirect (Commons categories). Only A can support a value on its own; a row whose
evidence is only C or D is marked low-evidence and must reach a human.

## Immutability, enforced by the database

```sql
create trigger translations_immutable_update before update on translations
when old.status in ('verified','reviewed')
begin select raise(abort,
  'verified/reviewed rows are immutable; insert a superseding proposal instead'); end;

create trigger translations_immutable_delete before delete on translations
when old.status in ('verified','reviewed')
begin select raise(abort, '...'); end;

create trigger translations_review_requires_reviewer before insert on translations
when new.status in ('verified','reviewed') and (new.reviewer is null or trim(new.reviewer) = '')
begin select raise(abort, 'verified/reviewed rows need a reviewer'); end;
```

A correction therefore arrives as a **new** row whose `supersedes_id` points at
the old one. The old row stays for audit; readers take the newest non-quarantined
row per `(sense_key, language)`.

## Migration, backup, rollback

```
python backend/tools/migrate_translations.py --dry-run --data-version <assetVersion>
python backend/tools/migrate_translations.py           --data-version <assetVersion>
python backend/tools/migrate_translations.py --rollback data/build/translations.db.bak-<stamp>
```

* Backup uses SQLite's backup API, not a file copy, so a live WAL cannot produce
  a torn copy. The backup name carries a UTC stamp; its sha256 is printed for
  identification only — backups are compared by **content**
  (`schema.snapshot()`: schema version + table inventory + row counts), because
  SQLite may rewrite page layout, so equal bytes are not guaranteed.
* `--dry-run` prints what would happen and creates nothing (verified: file absent
  after a dry run).
* Rollback refuses a backup that is not in the database's own directory, moves
  the current file aside as `*.rollback-<stamp>` instead of deleting it, and
  removes stale `-wal`/`-shm` sidecars before restoring.
* A migration that is already at the target version exits with
  `already at version 1, nothing to do`.

Applied for real on 2026-11-09: `data/build/translations.db`, schema 1, 61,440 B,
`versions` seeded with component `schema` and `dictionary=2026-11-09.3`.

Rehearsed on a copy of that real store: snapshot taken, one `evidence` row
written, backup taken, an unrelated write made, rollback executed →
`content_restored = True` (schema 1, `evidence` back to 0 rows), migrated file
kept aside as `*.rollback-*`.

Tested in `backend/tests/test_translations_schema.py` — **8 passing**:

1. fresh migrate creates all four tables plus the triggers, `user_version = 1`
2. a `reviewed` row cannot be updated or deleted (both abort)
3. a superseding `ai_unverified` proposal with `supersedes_id` is accepted
4. illegal statuses and a `verified` row without a reviewer are rejected
5. migrating an existing v0 file takes a backup named `*.bak-<stamp>`
6. rollback restores the previous file's content byte-qualitatively — schema
   version and row counts return to the pre-migration values — and keeps the
   migrated file aside
7. dry run creates no file
8. `sense_key` is stable under whitespace/case noise and differs per gloss

## Audit result (read-only, `docs/PHASE1-AUDIT.md`)

| Metric | Value |
|---|---|
| senses | 198,306 |
| with a Nepali value | 3,245 (1.6%) |
| empty | 195,061 |
| Devanagari only (`ok`) | 3,230 |
| Latin letters inside Devanagari (`latin_mix`) | 7 — needs script review |
| Devanagari + digits | 8 — acceptable for numbers/units |
| placeholder / copy-of-English / wrong script | **0 / 0 / 0** |
| distinct Nepali texts reused across different glosses | 40 |

Coverage by frequency band (this is where users actually look):

| band | senses | with Nepali | coverage |
|---|---|---|---|
| 1–1,000 | 3,910 | 775 | 19.8% |
| 1,001–5,000 | 11,618 | 1,296 | 11.2% |
| 5,001–20,000 | 30,930 | 839 | 2.7% |
| 20,001+ | 142,219 | 334 | 0.2% |
| no freq rank | 9,629 | 1 | 0.0% |

Coverage by domain: general 1.8%, everyday 1.8%, people_society 1.7%,
transport 1.6%, geography_environment 1.0%, language 0.9%, nature 0.8%,
technology 2.3%, business 1.5%, science_medicine 1.6%, tools_instruments 1.3%.

## Issues found, with severity

| Severity | Issue | Count | Why it matters |
|---|---|---|---|
| blocker | no Nepali value at all | 195,061 | empty Nepali box in the app |
| blocker | `hsk_level` unusable — every non-null value is 5 | 2,477 | HSK 1–3 queues are empty; an HSK launch gate cannot be computed |
| blocker | `pos_primary` empty | 198,230 senses / 123,596 entries | no noun/verb filter, so neither "concrete nouns" nor "skip function words" exists |
| major | proper nouns and 单位/化学式-like glosses mixed with core vocabulary | — | they would be translated and reviewed at the same cost as core words |
| review | Latin letters inside a Nepali value | 7 | legitimate for acronyms/units; flag, do not reject |
| review | same Nepali word attached to different glosses | 40 | sense-aware termbase must resolve these before reuse |

`hsk_level` and `pos_primary` are **not** fixable by an agent: no source list for
HSK 1–6 exists in the repo (only `hsk5_import.report.json`, which is where the
current all-5 values came from), and CC-CEDICT's part-of-speech markers were
never parsed into the column. Both are deterministic backfills and are the
prerequisite for Phase 3 stratified sampling.

## What this phase deliberately does not do

No agent, no model calls, no writes to any Nepali value. The store is empty on
purpose: the first rows will be written by Phase 5, and only into
`translations` with status `ai_unverified`.
