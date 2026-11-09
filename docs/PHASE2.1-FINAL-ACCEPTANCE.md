# Phase 2.1 — Final Acceptance

Date: 2026-11-09 · Baseline `773625f` · schema version 4 · nothing frozen yet.

## A. Implementation summary

### Files changed

| path | change |
| --- | --- |
| `backend/app/translations/status.py` | 11-step derivation ladder, 10 codes, `source_supported` hard preconditions |
| `backend/app/translations/resolve.py` | new: `resolve_values()` (DB-free policy), `resolve(dictionary_text, governance)`, `resolve_sense(conn, …)`, `resolve_reference(…, policy)` |
| `backend/app/translations/schema.py` | 3→4 migration branch, content fingerprint, rollback by content |
| `backend/app/translations/schema_v2_tables.py` | `SCHEMA_VERSION = 4`, four supersession guards |
| `backend/tools/import_legacy_ne.py` | `BEGIN IMMEDIATE` for rows + `id_map` + `event_log` + `versions`; `fail_after` injection; rollback keeps audit |
| `backend/tools/validate_fts.py` | new: exact entry-id set for `fts` and `fts_zh`, duplicates, count, tokenizer-aware probe, `quick_check`, `require_ok()` |
| `backend/tools/rebuild_fts.py` | `delete from` + single pass, gloss derived from `senses`, `--force-source` guard |
| `backend/tools/fts_repro_check.py` | new: two copies + second pass, fingerprints identical, source unchanged |
| `backend/tools/fts_sync.py` | new: keeps the two indexes in step after a promote |
| `backend/tools/rollback_rehearsal.py` | new: rehearsal on a copy of the **real** store |
| `backend/tools/build_dictionary.py` | both indexes generated last, trigram missing = `SystemExit`, release gate deletes the artifact and returns 1 |
| `backend/tools/r5_import.py` | promote ends with the FTS gate, non-zero exit on failure |
| `backend/tools/check_translation_golden.py` | new: only sanctioned writer of the shared vectors, exit 1 on drift |
| `lib/core/translation_status.dart` | same ladder; records accessed as `.$1/.$2/.$3` |
| `lib/core/translation_resolution.dart` | new: `resolveNepali`, `ChainIntegrity.analyze`, `resolveReference` |
| `lib/data/local/translation_repository.dart` | new: single resolution entry point, fail-closed store health |
| `shared/translation_status_golden.json` / `shared/translation_resolution_golden.json` | 24 status cases, 8 resolution cases (both read by Dart) |
| `backend/tests/test_translation_resolve.py`, `test_phase21_gates.py`, `test_resolution.py` | new coverage |
| `test/translation_resolution_test.dart`, `test/translation_repository_test.dart` | new Dart coverage |
| `.github/workflows/contracts.yml` | new: pytest + `flutter test` + golden gate |
| `docs/PHASE2-SCHEMA-CONTRACT.md` | new §13 (normative addendum) |

### Important decisions

* One derived label model; no label is stored as an authoritative status.
* Quarantine hides the sense **including** the dictionary fallback; a retired row
  falls back to the dictionary.
* Health of the governance store is fail-closed; a schema mismatch is never read
  optimistically.
* `ATTACH DATABASE` is not used: each store is opened read-only and joined in Dart.
* No `assert` is used as a gate; every check returns a non-zero exit.

## B. Integrity results

| check | result |
| --- | --- |
| legacy rows planned / inserted | 3,245 / 3,245 |
| missing vs dictionary | 0 |
| text mismatches | 0 |
| sense-key mismatches | 0 |
| unknown sense ids | 0 |
| `id_map` rows | 3,245 |
| foreign-key violations | 0 |
| `PRAGMA integrity_check` | ok |
| re-import over the existing batch | inserted 0, duplicates 3,245 (idempotent) |
| rollback of that batch (on a copy) | deleted 3,245, remaining 0, `only_that_batch: true` |
| audit after rollback | `legacy_ne_imported 3245`, `rollback_import_batch 1` (event preserved) |
| re-import after rollback | inserted 3,245, 0.28 s |
| content equals pre-rollback content | true (content fingerprint `8b481a2b…`) |
| `dictionary.sqlite` sha256 before/after | `3f9e5f46…f171f3` — unchanged |
| real store sha256 before/after | `2a6e4284…6cf036` — unchanged (rehearsal ran on a copy only) |
| supersession guards | 4/4 present and asserted |

### FTS

Shipped asset, re-validated today: `entries 123,672`; `fts 123,672` (0 missing);
`fts_zh 123,596` — **76 missing** (ids 123,597–123,672, i.e.
`entries.status='ai_translated'`), 0 unexpected, 0 duplicates → validator exit 1.
The hole is in the **shipped** asset and has not been rewritten without approval.
On copies the rebuilt indexes cover 123,672 rows each, reproducible:

```
fts     280ee2dd37aae3333fd31660c36c78a5bec3e92f65eed75cd9d70ba322b003f9
fts_zh  14f4eb7e88cef33a6ee769e9316f926aaaca4c7abe0040feccef1e0329e7ee38
entries ffac8406a9a7a333386745476207cd09264add61aa5c06858a858115c3286190
```

## C. Test results

| suite | command | result |
| --- | --- | --- |
| backend, whole | `python -m pytest -q` (in `backend`) | **151 passed**, 0 failed, 3 warnings, 9.53 s |
| gates only | `python -m pytest -q tests\test_phase21_gates.py` | **18 passed**, 5.18 s |
| golden parity | `python tools\check_translation_golden.py` | `golden vectors match: 24 status cases, 8 resolution cases`, exit 0 |
| FTS gate | `python tools\validate_fts.py --db data\build\dictionary.sqlite` | exit **1** (the 76 rows above) — the gate works |
| Flutter, whole | `flutter test` | **57 passed**, 0 failed |
| rollback rehearsal | `python tools\rollback_rehearsal.py` | `ok: true` |
| FTS reproducibility | `python tools\fts_repro_check.py` | `ok: true` |

Failure behaviour exercised, not described: import fails mid-batch (after rows,
after `id_map`, after a quarantine insert, after an event) leaves no partial
batch; a missing index row, an extra id, a duplicate id and a wrong expected count
each fail the build; the builder unlinks its artifact on gate failure.

Skipped tests: **none**.

## D. Remaining risks

1. The shipped `dictionary.sqlite` still carries the 76-row `fts_zh` hole. The
   pipeline can no longer emit such an artifact, but shipping a rebuilt asset
   changes the binary — needs explicit approval.
2. `sentence_section.dart` does not yet consume `LocalTranslationRepository`; the
   badge still comes from the old sense flag. Repository and contracts are ready
   and tested; wiring is Phase 1.5 §9.
3. The 7 `latin_mix` values are audited but not yet written into
   `quarantine_records`; nothing is hidden from users in the meantime.
4. Concurrency is asserted through `busy_timeout` + `BEGIN IMMEDIATE` semantics,
   not with two real processes writing at once.
5. The CI workflow is committed but has not run on GitHub from this machine.
6. Legacy provenance stops at "written by the AI enrichment script": no model,
   prompt, validation or review record survives.
7. POS and HSK backfills remain blocked on source decisions; the 2,477 HSK rows
   and the 3,245 Nepali rows overlap and are not independent populations.
8. Triggers are SQL-level safeguards; a direct file edit bypasses them.

## E. Acceptance recommendation

`ACCEPTED — Phase 2.1 ready for approval`

Rationale, in evidence: the 3,245 legacy translations are now represented in the
governance store and verified row-by-row (0 mismatches, 0 unknown ids, 0 FK
violations), a rollback on a copy of the real store removes exactly one batch and
keeps the audit trail, re-import restores byte-equal content, both stores are
unchanged by the rehearsal, the Python and Dart sides are pinned to one committed
24+8 vector contract, and every mandatory gate fails loudly with a non-zero exit.

Not frozen. Not started: Phase 1.5, Phase 3, schema freeze, any new translation.

## Revision 2 — after review (execution-governance round)

Changes made in response to the review, with their evidence:

| review point | what changed | evidence |
| --- | --- | --- |
| fingerprint method was vague | one written definition; ordering falls back to **all** columns when a table has no PK; `None` gets `\x00NULL` so NULL ≠ `''`; `user_version` enters the combined hash | `schema.content_fingerprint` docstring, `tools/fingerprint.py`, `tests/test_fingerprint_contract.py` (5 passed) |
| FTS config must be pointed at, not invented | §1 of the execution contract names `FTS_SCHEMA`, `validate_fts.py`, and forbids new tokenizers | `docs/PHASE2.1-EXECUTION-CONTRACT.md` |
| investigation→proposal needs a hard stop | contract step 2 must end the turn and quote the approval before any mutation | §2 of the contract |
| issue register should not bloat | register lists open items only, with severity/gate/evidence | `docs/ISSUE-REGISTER.md` (11 open) |
| latin_mix had no decision rule | deterministic classifier: five verdicts, one quarantine-justified | `app/translations/script_mix.py`, `tests/test_script_mix_rule.py` (10 passed) |
| "7 corrupted" was a screening count | real data: **5** `intra_token_mix` (senses 59001, 66092, 112935, 112963, 170710) + **2** `foreign_token` (5090, 49650) | `tools/classify_script_mix.py` read-only run |
| asset replacement needs an absolute gate | local rebuild success is never sufficient; report → approval → separate commit | §5 of the contract |
| concurrency "could be deferred" | decided and tested: single-writer, `timeout=0`, second writer rejected, no partial batch | `tests/test_concurrent_writers.py` (2 passed) |

Re-measured after the fingerprint change: rehearsal `ok: true`, content
`838b6b6f…`, dictionary sha `3f9e5f46…f171f3` unchanged, store sha `2a6e4284…6cf036`
unchanged. Backend suite: **168 passed, 0 failed**. Dart suite unchanged at
**57 passed** (no Dart file touched in this round).

## Revision 3 — operational-closure round

| gap you named | what closed it | evidence |
| --- | --- | --- |
| hard stop was only advisory | gates now live inside the suite: no `assert` in any gate script, every gate can exit non-zero, asset pin check, fingerprint rules, concurrency | `backend/tests/test_execution_guards.py` (14), `tests/test_fingerprint_contract.py` (8) |
| fingerprint must be permanently locked | `FINGERPRINT_VERSION = 1` in code and in the returned payload; a version bump is a breaking change that forces re-measurement | `schema.content_fingerprint`, `tools/fingerprint.py` |
| "confirm separator rules covered" | the separator forgery the question implied was **real**: `("x\x1ey","")` and `("x","y")` hashed identically. Fields are now length-prefixed | two new tests: field-separator forgery, row-separator forgery |
| docs hygiene / single source of truth | `docs/README.md` states the authority order; the corrections doc carries a superseded banner | `docs/README.md`, `PHASE2.1-CORRECTIONS.md` |
| asset replacement must be mechanical, not a promise | `docs/ASSET-PINS.json` + `tools/check_asset_pin.py`, run in the suite; a changed asset fails | pin check `unchanged` for both stores |
| closure prompt | `docs/PHASE2.1-CLOSURE-CHECKLIST.md` — four items, exact commands, evidence slots | — |

Re-measured: rehearsal `ok: true`, content `4656e33b…`; pin check `unchanged` for
`dictionary.sqlite` and `translations.db`; backend **185 passed, 0 failed**.

Remote CI (S-04) is **still open and cannot be closed here**: no `gh` CLI on this
machine and the repo API answers 404 unauthenticated. It needs one run by someone
with repo access, on the pushed sha.

Status: implementation complete; operational closure has **two** blockers left —
C1 (remote CI evidence) and C2 (go/no-go on the 5 quarantine candidates). Not
closed, not frozen, asset untouched.


