# Phase 2.1 — Execution Contract (authoritative for any coding agent)

This is the instruction set a coding agent must follow for Phase 2.1 closure and
the approval gate that follows it. It is normative; where it disagrees with a
report or with chat text, this file wins.

## 0. Standing rules

1. Preserve every original dictionary record and every existing Nepali value.
2. Never silently overwrite, delete or reinterpret a translation.
3. Never set `human_verification='verified'` from a pipeline, script, import or
   migration — only an authorised verification record may, and the trigger must
   refuse everything else.
4. No resolution logic in widgets; `lib/data/local/translation_repository.dart`
   is the only entry point.
5. No Python `assert` as a mandatory check. Every gate is an explicit branch
   returning a non-zero exit code.
6. A failed mandatory check stops the operation and must not leave a shippable
   artefact.
7. Phase 1.5, Phase 3, schema freeze, and any new translation work remain
   blocked until written approval.

## 1. Authority pointers (do not invent configuration)

| what | authoritative source |
| --- | --- |
| FTS tables, tokenizer, columns | `backend/tools/build_dictionary.py` → `FTS_SCHEMA` (unicode61 for `fts`, `tokenize='trigram'` for `fts_zh`) |
| FTS validation | `backend/tools/validate_fts.py` (entry-id set, duplicates, count, `quick_check`) |
| content fingerprint | `backend/app/translations/schema.py` → `content_fingerprint` (definition reproduced in `backend/tools/fingerprint.py`) |
| status labels | `backend/app/translations/status.py`, `lib/core/translation_status.dart`, `shared/translation_status_golden.json` |
| resolution precedence | `backend/app/translations/resolve.py` → `resolve_values`, `lib/core/translation_resolution.dart` → `resolveNepali`, `shared/translation_resolution_golden.json` |
| golden updates | `backend/tools/check_translation_golden.py --update` only |
| script-mix rule | `backend/app/translations/script_mix.py` |

An agent may not add a tokenizer, a content table, a column, or a "similar"
fingerprint method because one seemed plausible.

## 2. Work sequence — with a hard stop

```
investigate → propose remediation → [STOP: written approval] → mutate → validate → report
```

Step 2 is a deliverable, not a formality. After the proposal the agent must end
the turn and wait. Continuing into mutation without an explicit approval line
(quoted verbatim from the reviewer) is a contract violation, even when the
proposal looks obviously correct and the change is one line.

Investigation is read-only:
* open SQLite through `file:…?mode=ro` URIs,
* never write to `dictionary.sqlite`,
* never write to `translations.db` outside an approved mutation step,
* never create a quarantine record during investigation.

## 3. Scope protection (absolute)

A change is in scope only if it is named in the approved proposal. Out of scope,
without exception: refactors "while here", comment sweeps, dependency bumps,
widget wiring, other tests, formatting of untouched files, new abstractions for
one call site. Unrelated changes must be reported and reverted, not shipped
inside a gate commit.

## 4. FTS rebuild — deterministic specification

* Rebuild both indexes from `entries` in one pass **after** all entries and senses
  are written; never from a captured `MAX(entry_id)`, never from a fixed ID range.
* Empty with `delete from <table>`; `insert into fts(fts) values('delete-all')` is
  invalid for a plain fts5 table.
* `english` is not an `entries` column; derive it from `senses.gloss_en` in sense
  order (the builder's `_ENTRY_ENGLISH` expression is the authority).
* `trigram` must be quoted: `tokenize='trigram'`; a missing tokenizer is a
  `SystemExit`, never a silent downgrade.
* `fts` (unicode61, 6 columns, `entry_id` UNINDEXED) and `fts_zh` (trigram, 4
  columns + `entry_id`) hold the same entry ids; a 1–2 character query returning
  0 hits is expected behaviour, not a defect signal.
* `--rebuild` refuses to touch the shipped asset by default; `--force-source` is
  for a disposable copy only.
* Rebuild must be reproducible: two copies plus a second pass produce identical
  per-index fingerprints (`backend/tools/fts_repro_check.py`).

## 5. Shipped asset replacement (absolute gate)

Local rebuild success is **never** sufficient.

Replacing `backend/data/build/dictionary.sqlite` requires, in this order:

1. an evidence report: exact-id sets before/after, the 76 missing ids enumerated,
   rebuild fingerprints, reproducibility output, source sha before/after,
   integrity check, and the user-visible consequences;
2. explicit human approval of that report;
3. the replacement committed as its own change, with the old asset's sha
   recorded.

Until all three happen the shipped asset stays as it is — including with the
known 76-row `fts_zh` hole. A gate that blocks the *pipeline* from producing such
an asset does not authorise touching the asset itself.

## 6. Import and rollback

* Atomic: rows + `id_map` + `event_log` + `versions` inside one `BEGIN IMMEDIATE`.
* Failure at any point leaves nothing behind (inject at rows, at `id_map`, at a
  quarantine insert, at the event row).
* Rollback is batch-scoped: it deletes only that batch's rows and **preserves**
  the batch's audit events, appending one `rollback_import_batch` event.
* Re-import after rollback must reproduce the same content columns (whitespace,
  NULL-ness and text included), not merely the same row count.

## 7. Fingerprint — one definition, no variants

Per `schema.content_fingerprint`, reproduced in `tools/fingerprint.py`: every user
table; every column in declared order; `str()` values; `None` → `\x00NULL`;
`\x1e` between fields and `\x1d` between rows; ordering by primary key when a
table has one, otherwise by all columns; per-table sha256 + row count; combined
sha256 over `v<user_version>` and `table|rows|sha` sorted by table.

No NFC/NFKC, no whitespace collapsing, no case folding, no `rowid`, no file bytes,
no WAL or page-layout state. A fingerprint is evidence of *equal values*, not of
a recoverable file, and never a substitute for an integrity check.

## 8. Concurrency (decided, not deferred)

The store is **single-writer**. Writes open with `BEGIN IMMEDIATE`; a contended
writer receives `SQLITE_BUSY` immediately (`schema.connect(..., timeout=0)`)
instead of blocking and later succeeding at an unpredictable point. Callers may
pass a timeout deliberately; the importer does not. Concurrent writers are
rejected, not serialised — that is the supported deployment model, and it is
tested in `backend/tests/test_concurrent_writers.py`.

## 9. Script-mix decision rule (§14)

`app/translations/script_mix.py` decides; nothing else may.

| verdict | meaning | action |
| --- | --- | --- |
| `intra_token_mix` | Latin/Cyrillic letters **inside** a Devanagari word | the only quarantine-justified case; preserve original text + rule + batch id |
| `foreign_token` | a pure Latin token beside Devanagari ("C", "Zhuge Liang") | keep visible, label/attribution note, never quarantine |
| `no_devanagari` | no Devanagari at all | escalate for a human decision, never auto-quarantine |
| `clean` | one script per word | no action |

Measured on the real dictionary: 7 values carry Latin/Cyrillic letters → **5**
`intra_token_mix` (शuai उपनाम, केही आश्चर्य नै हoinu, बatti ×2, दृढतापूर्वक पурсnu)
and **2** `foreign_token` (सूची अक्षर C, Zhuge Liang को सम्मान नाम). The earlier
"7 corrupted" figure was a screening count, not a verdict; the decision collapses
it to 5 with 2 legitimate strings, and none of them may be deleted.

A script verdict is typographic evidence only — it never claims semantic
correctness, and a clean string may still be a wrong translation.

## 10. Acceptance criteria (all must hold, with executed evidence)

1. Legacy import: 3,245 rows, 0 text/key mismatches, 0 unknown ids, 0 FK errors,
   `quick_check` ok.
2. Rollback on a copy of the real store: exactly one batch removed, audit kept,
   re-import restores equal content, both stores unchanged (sha) .
3. Shipped asset fingerprint before/after: unchanged by any rehearsal.
4. FTS: gate fails on the known hole and passes on a rebuilt copy; reproducible.
5. Golden parity: 24 + 8 cases match; drift exits non-zero; CI runs both suites.
6. Repository resolution: 13+ Dart tests including real two-database resolution,
   missing/empty/corrupt store, schema mismatch, quarantine, fork, cycle,
   cross-sense.
7. Status edges: verified+failed, quarantined+verified, direct-without-`ne`,
   direct-without-defensible-sense, llm+failed, source_import+incomplete, missing
   provenance, user correction superseding AI.
8. Concurrency: second writer rejected; no partial batch.
9. Clean worktree; commit + push; remote head reported by sha.
10. Repeat the whole suite from a clean checkout and publish the remote CI result.

## 11. Rejection criteria (any hit ⇒ `REJECTED`)

* a gate downgraded to `assert`, a warning, or a skip;
* a shipped asset changed without §5;
* a quarantine or deletion applied during investigation;
* Phase 1.5 or Phase 3 code, tests or docs started;
* a status label invented that is not in the shared contract;
* unexecuted tests reported as passing, or a suite reported without counts;
* a fingerprint computed by a second method.

## 12. Report shape

Sections A (implementation), B (integrity evidence), C (tests with commands and
counts), D (remaining risks), E (`ACCEPTED` / `REJECTED` with one-line reasoning).
Plus: updated issue register (open items only), commit sha, remote CI result, and
confirmation that the shipped asset and every stored Nepali value are unchanged.

Then stop. No progression, no freeze, no Phase 1.5.
