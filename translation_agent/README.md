# translation_agent

Candidate-only Nepali translation generation for `trilingual_dictionary`.

This subsystem **generates candidates and nothing else**. It cannot approve,
cannot import, cannot mark anything human-verified, and cannot open the shipped
dictionary or the governance store. Those refusals are enforced in code, not in
prose: see `src/translation_agent/config.py` and
`src/translation_agent/ledger/sqlite_ledger.py`.

## Status — what is actually proven

Proven by executed tests on Linux, Python 3.12.11 / SQLite 3.49.1:

- 110 tests pass (0 xfailed); the suite needs no network and no credentials and
  survives randomized order (seeds 20261109, 991, 2026).
- Batch atomicity: a provider failure injected after *n* successful calls leaves
  **zero** candidate rows, zero request rows and zero attempt rows.
- Idempotency: re-running the same senses yields `inserted 0, skipped 6`,
  request fingerprints unchanged.
- Actor restrictions: `generation_agent` cannot move a candidate to `approved`
  or `imported`; only `human_reviewer` approves and only `parent_importer` imports.
- Production refusal: name, path marker, ambiguity rules (`file:`, `?mode=rw`,
  trailing whitespace), inode identity (hard links) and content identity
  (byte-identical copies) — all refused before any connection is opened. Hard-link
  protection requires the protected manifest; `guard` reports whether it is active.
- Raw provider payloads are secret-redacted and size-capped before storage.
- Export refuses when no candidate is approved (exit 1).
- Schema verification is structural (columns, types, nullability, keys, indexes,
  foreign keys, DDL) and never repairs; tampering fails closed.
- Rollback is non-destructive: payload, provenance and events survive.
- Request identity is input-aware (v2): a corrected gloss yields a new request,
  and the resolved provider parameters (`provider.parameters()`, stored as
  canonical JSON) are part of that identity.
- Schema verification also compares index definitions, so a changed expression
  index, collation, sort order or partial predicate fails closed.

**Not proven, and deliberately not faked:** quality of actual Nepali output.
The only provider wired up is the deterministic fake. There is no pilot run
against the 3,245 real senses or the 50-sense pilot list, because that requires
the real `dictionary.sqlite` and `translations.db`, which are not here.

## Commands

```bash
python3 -m pytest                                  # 110 passed
PYTHONPATH=src python3 -m translation_agent.cli init     --db /tmp/ta/candidates.db
PYTHONPATH=src python3 -m translation_agent.cli run-fake --db /tmp/ta/candidates.db --batch pilot-001
PYTHONPATH=src python3 -m translation_agent.cli status   --db /tmp/ta/candidates.db
PYTHONPATH=src python3 -m translation_agent.cli export   --db /tmp/ta/candidates.db --out /tmp/ta/approved.json
PYTHONPATH=src python3 -m translation_agent.cli guard                                  # which protections are active (incl. manifest age/freshness)
PYTHONPATH=src python3 -m translation_agent.cli retention --db /tmp/ta/candidates.db   # plan; add --apply to erase expired payloads
```

## Layout

```
src/translation_agent/
  config.py                      # env config + production-database guard (name/marker/identity/ambiguity)
  domain/identity.py             # NFC normalization v1, canonical JSON, hashes, request fingerprint v2
  domain/models.py               # frozen value objects
  providers/base.py              # provider protocol + error classes
  providers/fake_provider.py     # deterministic provider with fault injection
  generation/pipeline.py         # prompt -> provider -> parse -> validate -> ledger
  validation/validator.py        # Devanagari / script-mix / echo rules
  ledger/schema.py               # v2 DDL (single source of truth)
  ledger/schema_verifier.py      # full structural verification, fail closed
  ledger/sqlite_ledger.py        # the single writable path + state machine + busy retry
  audit/raw_response_store.py    # redaction + retention metadata
  audit/retention.py             # explicit retention operation (payloads only)
  export/candidate_export.py     # approved-only export with checksum
fixtures/senses/pilot_fixture.json   # synthetic senses, never production rows
scripts/capture_pins.py              # read-only pin capture
scripts/safe_copy.py                 # online-backup copy with integrity check
scripts/protect_manifest.py          # capture dev/ino/sha256 for the guard
docs/FINGERPRINT-CONTRACT.md         # v1 frozen, v2 input-aware
docs/SECURITY-CONTRACT.md            # guard controls and their limits
staged/translation-agent-tests.yml   # CI workflow, waiting to be moved into .github/workflows
docs/PILOT-PROTOCOL.md               # pre-registered pilot rules, 8 open human decisions
```

## What must not change without an approved contract revision

1. `content_fingerprint` (production, v1) and the hashes here are different
   functions with different lifetimes. Never compare them.
2. Candidate `quarantined` ≠ production `quarantine_records`. A rejected
   candidate is simply not exported; it never suppresses production text.
3. Provenance is mandatory: provider, model, prompt version, prompt checksum,
   request fingerprint, normalization version — all stored per candidate.
