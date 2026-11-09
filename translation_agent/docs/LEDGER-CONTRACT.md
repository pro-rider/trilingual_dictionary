# CANDIDATE LEDGER CONTRACT (v0.3)

Owner: this subsystem. Contract version: `TA-CONTRACT-0.3`.
Schema version: `3`. Ledger filename: `candidates.db` (never `translations.db`).

## Ownership

One writable database per run. One module (`ledger/sqlite_ledger.py`) is the
only code allowed to issue `INSERT`/`UPDATE`/`DELETE`. Providers, validators and
exporters receive no connection object.

## Tables

| table | purpose |
| --- | --- |
| `ledger_meta` | `schema_version`, `contract_version` |
| `generation_requests` | one row per *resolved generation input*: sense, source text, pinyin, gloss, target language, provider, model, resolved model parameters (canonical JSON), prompt, variant |
| `candidates` | one row per normalized candidate text |
| `candidate_events` | append-only actor/transition audit |
| `provider_attempts` | every attempt, including failures |
| `raw_responses` | redacted, size-capped payloads |

Uniqueness:

- `generation_requests.request_fingerprint` is UNIQUE → idempotency, over the
  v2 (input-aware) fingerprint.
- `candidates(candidate_hash, sense_key, target_language, COALESCE(variant_key,'base'))`
  is UNIQUE → exact duplicate suppression **within a variant**. An intentional
  variant keeps its own row even when its text equals the base candidate's:
  variant coexistence is the normal case, not an error.
- `generation_requests.state` is `active` unless a rollback retired the batch.

## Request identity (v2)

Fingerprint v1 identified the *configuration*: sense key, language, provider,
model, prompt version and prompt checksum. A corrected source gloss therefore
kept the same v1 fingerprint and the pipeline skipped the corrected sense.

v2 hashes the whole resolved input — source word, pinyin, gloss,
`source_revision_hash`, target language, provider, model, model parameters,
prompt version and checksum, the rendered prompt hash, output schema version and
`variant_key`. `request_fingerprint_v1` is still written alongside so historical
values never drift. Definition: `docs/FINGERPRINT-CONTRACT.md`.

## Identity

```
candidate_hash = sha256(canonical_json{
  fingerprint_version: 1,
  normalization_version: "nfc-ws1-v1",
  target_language: "ne",
  text: <NFC + whitespace-collapsed text>
})
```

The hash identifies normalized *content*. It does not decide linguistic
equivalence, and it is never compared with the production `content_fingerprint`.

## Normalization

`nfc-ws1-v1`: Unicode NFC; runs of whitespace (including NBSP/ZWSP) collapsed to
a single space; ends trimmed. Case, punctuation, diacritics and NFKC folding are
**not** applied. Original text is stored verbatim in `original_text` and is
never overwritten.

## State machine

States: `generated`, `validated`, `needs_review`, `approved`, `imported`,
`quarantined`, `rejected`, `revoked`, `rolled_back`.

| transition | permitted actors |
| --- | --- |
| generated → validated | `generation_agent` |
| validated → needs_review | `generation_agent` |
| generated/validated → quarantined | `generation_agent` |
| needs_review → approved | `human_reviewer` |
| needs_review → rejected | `human_reviewer` |
| approved → imported | `parent_importer` |
| approved/imported → revoked | `authorized_admin` |

Any other pair is refused with `StateTransitionRefused`. There is no path from
any state to a human-verification claim: that concept does not exist in this
ledger at all.

## Transactions

Every batch is one `BEGIN IMMEDIATE` … `COMMIT`. `requests`, `candidates`,
`events`, `attempts` and `raw_responses` are written inside that single
transaction. A failure at any point rolls back everything, including audit rows
collected for the batch. Verified by
`tests/test_atomicity.py::test_failure_after_two_calls_leaves_no_rows`.

`CONTRACT CHANGE (v0.3)` — `rollback_batch(batch_id)` is **non-destructive**:

- it writes one `rolled_back` event per candidate (once; idempotent),
- it sets `candidates.state = 'rolled_back'` and `generation_requests.state = 'rolled_back'`,
- it keeps the payload, provenance, request linkage, review history and events.

Deleting rows disconnected the audit event from the thing it described and let
a later retry silently recreate the same text. Retention of raw payloads is a
separate operation (`audit/retention.py`) that erases payload bytes only.

## Failed batches and the audit question

`CONTRACT DECISION (v0.3)` — a batch that aborts persists **nothing**, including
`provider_attempts`. Atomicity wins over partial history: a re-run must never
observe half-written rows it cannot explain.

What replaces it: the error is raised with the provider error *class* preserved
(`ProviderTimeout` / `ProviderInvalidJSON` / `ProviderFailure`), the message names
the failing sense and the exhausted attempt count, and it is asserted to carry
no secret material (`tests/test_atomicity.py::test_failed_batch_leaves_no_attempt_rows_and_reports_redacted_errors`).
If an external failure log is wanted later, it must be a separate sink, never a
weakening of the transaction.

## Concurrency

`timeout=0.0` plus explicit `BEGIN IMMEDIATE` means a second writer never waits
forever. The transaction helper retries on `SQLITE_BUSY`/`SQLITE_LOCKED` with
bounded exponential backoff (`busy_retries`, `busy_backoff_ms`), and raises
`LedgerBusy` when the budget is exhausted. Non-lock errors are never retried, and
a provider call is never repeated because persistence hit a lock.

## Failed batches and the audit question

`CONTRACT DECISION (v0.3)` — a batch that aborts persists **nothing**, including
`provider_attempts`. Atomicity wins over partial history: a re-run must never
observe half-written rows it cannot explain.

What replaces it: the error is raised with the provider error *class* preserved
(`ProviderTimeout` / `ProviderInvalidJSON` / `ProviderFailure`), the message names
the failing sense and the exhausted attempt count, and it is asserted to carry
no secret material (`tests/test_atomicity.py::test_failed_batch_leaves_no_attempt_rows_and_reports_redacted_errors`).
If an external failure log is wanted later, it must be a separate sink, never a
weakening of the transaction.

## Concurrency

`sqlite3.connect(timeout=0.0)` + `BEGIN IMMEDIATE`: a second writer gets an
immediate `SQLITE_BUSY` instead of an unbounded wait. Callers must treat BUSY as
"retry later", never as "write anyway".

## Schema verification

`SqliteLedger.__init__` verifies table set and `schema_version` before any write;
mismatch raises `LedgerSchemaMismatch` (fail closed). Verified by
`tests/test_security.py::test_schema_mismatch_fails_closed`.
