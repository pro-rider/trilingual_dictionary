"""Ledger DDL, version 2.

Kept in its own module so the schema *verifier* can build a pristine copy of
the expected schema and compare it against the live database, without importing
the ledger itself.

v2 changes (TASK 020):
* ``generation_requests`` records the source input and both fingerprints;
* ``generation_requests.state`` exists so a rollback can retire a request
  without deleting it;
* ``raw_responses.purged_at`` lets retention delete payloads while keeping the
  audit row.
"""

from __future__ import annotations


LEDGER_SCHEMA_VERSION = "3"
CONTRACT_VERSION = "TA-CONTRACT-0.3"
LEDGER_FILENAME = "candidates.db"

SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS ledger_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS generation_requests (
        request_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        sense_key TEXT NOT NULL,
        target_language TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        prompt_checksum TEXT NOT NULL,
        request_fingerprint TEXT NOT NULL UNIQUE,
        request_fingerprint_v1 TEXT,
        fingerprint_version INTEGER NOT NULL DEFAULT 2,
        variant_key TEXT,
        source_word TEXT,
        source_pinyin TEXT,
        source_gloss TEXT,
        source_revision_hash TEXT,
        rendered_prompt_sha256 TEXT,
        model_parameters TEXT,
        state TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS candidates (
        candidate_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL,
        batch_id TEXT NOT NULL,
        sense_key TEXT NOT NULL,
        target_language TEXT NOT NULL,
        original_text TEXT NOT NULL,
        normalized_text TEXT NOT NULL,
        normalization_version TEXT NOT NULL,
        candidate_hash TEXT NOT NULL,
        variant_key TEXT,
        state TEXT NOT NULL,
        rejection_reason TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS candidate_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id TEXT NOT NULL,
        batch_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        from_state TEXT,
        to_state TEXT NOT NULL,
        reason TEXT NOT NULL,
        at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS provider_attempts (
        attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        attempt_no INTEGER NOT NULL,
        status TEXT NOT NULL,
        latency_ms INTEGER,
        error_code TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS raw_responses (
        response_id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        bytes INTEGER NOT NULL,
        truncated INTEGER NOT NULL,
        retention_days INTEGER NOT NULL,
        purged_at TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_candidates_batch ON candidates(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_candidates_state ON candidates(state)",
    "CREATE INDEX IF NOT EXISTS idx_events_batch ON candidate_events(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_attempts_request ON provider_attempts(request_id)",
    "CREATE INDEX IF NOT EXISTS idx_requests_sense ON generation_requests(sense_key)",
    # Candidate identity: same text for the same sense is one row, but an
    # intentional variant is its own row.  COALESCE makes the base variant
    # (variant_key IS NULL) participate in uniqueness.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_identity "
    "ON candidates(candidate_hash, sense_key, target_language, COALESCE(variant_key, 'base'))",
)

EXPECTED_TABLES = {
    "ledger_meta",
    "generation_requests",
    "candidates",
    "candidate_events",
    "provider_attempts",
    "raw_responses",
}

EXPECTED_INDEXES = {
    "idx_candidates_batch",
    "idx_candidates_state",
    "idx_events_batch",
    "idx_attempts_request",
    "idx_requests_sense",
    "idx_candidates_identity",
}
