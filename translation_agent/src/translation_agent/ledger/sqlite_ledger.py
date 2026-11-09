"""Candidate ledger: the single writable path.

Invariants enforced by code, not by documentation:

* one connection class, one writable database, production paths refused by
  name, path marker, inode identity and content identity (see ``config``);
* every write goes through an explicit ``BEGIN IMMEDIATE`` transaction, with
  a bounded retry on ``SQLITE_BUSY``/``SQLITE_LOCKED`` — never an unbounded wait;
* the state machine is owned here, with actor restrictions;
* the generation agent can never move a candidate to ``approved``/``imported``;
* a failed batch leaves zero candidate rows and zero request rows;
* **rollback is non-destructive**: it retires rows into ``rolled_back`` and
  keeps the payload, provenance and history, so audit evidence survives;
* schema mismatches fail closed before any write, on the full structure (columns,
  types, nullability, keys, indexes, foreign keys, DDL), not just table names.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator, Sequence

from ..config import assert_not_production
from ..domain.models import CandidateDraft, ValidationResult
from .schema import (  # re-exported for existing imports
    CONTRACT_VERSION,
    EXPECTED_INDEXES,
    EXPECTED_TABLES,
    LEDGER_FILENAME,
    LEDGER_SCHEMA_VERSION,
    SCHEMA_STATEMENTS,
)
from .schema_verifier import LedgerSchemaMismatch, verify as verify_structure


AGENT = "generation_agent"
REVIEWER = "human_reviewer"
IMPORTER = "parent_importer"
ADMIN = "authorized_admin"
SYSTEM = "ledger"

STATES = (
    "generated",
    "validated",
    "needs_review",
    "approved",
    "imported",
    "quarantined",
    "rejected",
    "revoked",
    "rolled_back",
)

# (from_state, to_state) -> actors allowed to perform it
TRANSITIONS: dict[tuple[str, str], set[str]] = {
    ("generated", "validated"): {AGENT},
    ("validated", "needs_review"): {AGENT},
    ("generated", "quarantined"): {AGENT},
    ("validated", "quarantined"): {AGENT},
    ("needs_review", "approved"): {REVIEWER},
    ("needs_review", "rejected"): {REVIEWER},
    ("needs_review", "quarantined"): {REVIEWER},
    ("approved", "imported"): {IMPORTER},
    ("approved", "revoked"): {ADMIN},
    ("imported", "revoked"): {ADMIN},
    ("rejected", "needs_review"): {REVIEWER},
    ("rolled_back", "needs_review"): set(),  # terminal without a new batch
}


class LedgerError(RuntimeError):
    pass


class LedgerBusy(LedgerError):
    """Another writer held the database for longer than the retry budget."""


class StateTransitionRefused(LedgerError):
    pass


class DuplicateCandidate(LedgerError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_busy(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


class SqliteLedger:
    """The only component allowed to write candidates."""

    def __init__(
        self,
        path: str,
        create: bool = True,
        protected_manifest: str | None = None,
        busy_retries: int = 5,
        busy_backoff_ms: int = 20,
    ):
        self.path = assert_not_production(path, protected_manifest)
        self._busy_retries = busy_retries
        self._busy_backoff_ms = busy_backoff_ms
        self._conn = sqlite3.connect(
            self.path, timeout=0.0, isolation_level=None, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        if create:
            self._create_schema()
        self.verify_schema()

    # -- lifecycle -------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SqliteLedger":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _create_schema(self) -> None:
        with self.transaction():
            for statement in SCHEMA_STATEMENTS:
                self._conn.execute(statement)
            self._conn.execute(
                "INSERT OR IGNORE INTO ledger_meta(key, value) VALUES ('schema_version', ?)",
                (LEDGER_SCHEMA_VERSION,),
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO ledger_meta(key, value) VALUES ('contract_version', ?)",
                (CONTRACT_VERSION,),
            )

    def verify_schema(self) -> dict[str, str]:
        structure = verify_structure(self._conn)
        meta = {
            row["key"]: row["value"]
            for row in self._conn.execute("SELECT key, value FROM ledger_meta")
        }
        version = meta.get("schema_version")
        if version != LEDGER_SCHEMA_VERSION:
            raise LedgerSchemaMismatch(
                [
                    f"ledger_meta.schema_version is {version!r}, expected {LEDGER_SCHEMA_VERSION!r}"
                ]
            )
        contract = meta.get("contract_version")
        if contract != CONTRACT_VERSION:
            raise LedgerSchemaMismatch(
                [f"ledger_meta.contract_version is {contract!r}, expected {CONTRACT_VERSION!r}"]
            )
        meta["schema_fingerprint"] = structure["schema_fingerprint"]
        return meta

    # -- transactions ----------------------------------------------------
    @contextmanager
    def transaction(self, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """Explicit transaction with bounded exponential backoff on BUSY/LOCKED."""
        attempts = max(0, self._busy_retries)
        delay = max(0, self._busy_backoff_ms)
        begun = False
        last_busy: sqlite3.OperationalError | None = None
        for attempt in range(attempts + 1):
            try:
                self._conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            except sqlite3.OperationalError as exc:
                if not _is_busy(exc):
                    raise
                last_busy = exc
                if attempt == attempts:
                    raise LedgerBusy(
                        f"database stayed locked after {attempts} retr(ies): {exc}"
                    ) from exc
                time.sleep((delay * (2**attempt)) / 1000.0)
                continue
            begun = True
            break

        try:
            yield self._conn
        except BaseException:
            if begun:
                self._conn.execute("ROLLBACK")
            raise
        else:
            if begun:
                self._conn.execute("COMMIT")

    # -- writes ----------------------------------------------------------
    def commit_batch(
        self,
        *,
        batch_id: str,
        requests: Sequence[dict],
        candidates: Sequence[CandidateDraft],
        events: Sequence[dict],
        attempts: Sequence[dict],
        raw_responses: Sequence[dict],
    ) -> int:
        """Insert a whole batch atomically.  Returns candidate count.

        Any exception during this call rolls the entire batch back: no
        candidate, no request, no attempt, no raw response row survives.
        """
        inserted = 0
        with self.transaction() as conn:
            for request in requests:
                conn.execute(
                    """INSERT INTO generation_requests
                       (request_id, batch_id, sense_key, target_language, provider,
                        model, prompt_version, prompt_checksum, request_fingerprint,
                        request_fingerprint_v1, fingerprint_version, variant_key,
                        source_word, source_pinyin, source_gloss, source_revision_hash,
                        rendered_prompt_sha256, model_parameters, state, created_at)
                       VALUES (:request_id, :batch_id, :sense_key, :target_language, :provider,
                        :model, :prompt_version, :prompt_checksum, :request_fingerprint,
                        :request_fingerprint_v1, :fingerprint_version, :variant_key,
                        :source_word, :source_pinyin, :source_gloss, :source_revision_hash,
                        :rendered_prompt_sha256, :model_parameters, :state, :created_at)""",
                    request,
                )
            for draft in candidates:
                try:
                    conn.execute(
                        """INSERT INTO candidates
                           (candidate_id, request_id, batch_id, sense_key, target_language,
                            original_text, normalized_text, normalization_version,
                            candidate_hash, variant_key, state, rejection_reason,
                            created_at, updated_at)
                           VALUES (:candidate_id, :request_id, :batch_id, :sense_key,
                            :target_language, :original_text, :normalized_text,
                            :normalization_version, :candidate_hash, :variant_key,
                            :state, :rejection_reason, :created_at, :updated_at)""",
                        {
                            "candidate_id": draft.candidate_id,
                            "request_id": draft.request_id,
                            "batch_id": batch_id,
                            "sense_key": draft.sense_key,
                            "target_language": draft.target_language,
                            "original_text": draft.original_text,
                            "normalized_text": draft.normalized_text,
                            "normalization_version": draft.normalization_version,
                            "candidate_hash": draft.candidate_hash,
                            "variant_key": draft.variant_key,
                            "state": draft.state,
                            "rejection_reason": None,
                            "created_at": utc_now(),
                            "updated_at": utc_now(),
                        },
                    )
                except sqlite3.IntegrityError as exc:
                    raise DuplicateCandidate(
                        f"candidate already exists for {draft.sense_key}: {exc}"
                    ) from exc
                inserted += 1
            for event in events:
                conn.execute(
                    """INSERT INTO candidate_events
                       (candidate_id, batch_id, actor, from_state, to_state, reason, at)
                       VALUES (:candidate_id, :batch_id, :actor, :from_state, :to_state,
                        :reason, :at)""",
                    event,
                )
            for attempt in attempts:
                conn.execute(
                    """INSERT INTO provider_attempts
                       (request_id, provider, model, attempt_no, status, latency_ms,
                        error_code, created_at)
                       VALUES (:request_id, :provider, :model, :attempt_no, :status,
                        :latency_ms, :error_code, :created_at)""",
                    attempt,
                )
            for raw in raw_responses:
                conn.execute(
                    """INSERT INTO raw_responses
                       (request_id, payload, bytes, truncated, retention_days, created_at)
                       VALUES (:request_id, :payload, :bytes, :truncated, :retention_days,
                        :created_at)""",
                    raw,
                )
        return inserted

    def transition(self, candidate_id: str, to_state: str, actor: str, reason: str) -> str:
        if to_state not in STATES:
            raise StateTransitionRefused(f"unknown target state {to_state!r}")
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT state, batch_id FROM candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise LedgerError(f"unknown candidate {candidate_id!r}")
            from_state = row["state"]
            allowed = TRANSITIONS.get((from_state, to_state))
            if not allowed:
                raise StateTransitionRefused(
                    f"{from_state} -> {to_state} is not a legal transition"
                )
            if actor not in allowed:
                raise StateTransitionRefused(
                    f"actor {actor!r} may not perform {from_state} -> {to_state}"
                )
            conn.execute(
                "UPDATE candidates SET state = ?, updated_at = ? WHERE candidate_id = ?",
                (to_state, utc_now(), candidate_id),
            )
            conn.execute(
                """INSERT INTO candidate_events
                   (candidate_id, batch_id, actor, from_state, to_state, reason, at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (candidate_id, row["batch_id"], actor, from_state, to_state, reason, utc_now()),
            )
        return to_state

    def rollback_batch(self, batch_id: str, reason: str = "batch rollback") -> int:
        """Retire a batch into ``rolled_back`` — never delete its evidence.

        The payload, provenance, request link and event history all survive.
        Deleting them would disconnect the audit trail from the thing it
        describes, and a later retry could silently recreate the same text.
        """
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT candidate_id, state FROM candidates WHERE batch_id = ?", (batch_id,)
            ).fetchall()
            for row in rows:
                if row["state"] == "rolled_back":
                    continue
                conn.execute(
                    """INSERT INTO candidate_events
                       (candidate_id, batch_id, actor, from_state, to_state, reason, at)
                       VALUES (?, ?, ?, ?, 'rolled_back', ?, ?)""",
                    (row["candidate_id"], batch_id, SYSTEM, row["state"], reason, utc_now()),
                )
            conn.execute(
                "UPDATE candidates SET state = 'rolled_back', updated_at = ? "
                "WHERE batch_id = ? AND state <> 'rolled_back'",
                (utc_now(), batch_id),
            )
            conn.execute(
                "UPDATE generation_requests SET state = 'rolled_back' WHERE batch_id = ?",
                (batch_id,),
            )
        return len(rows)

    def purge_raw_payloads(self, response_ids: Sequence[int], reason: str = "retention") -> int:
        """Erase payload bytes but keep the raw-response row (audit linkage)."""
        ids = list(response_ids)
        if not ids:
            return 0
        stamp = utc_now()
        with self.transaction() as conn:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"""UPDATE raw_responses SET payload = '[PURGED]', bytes = 0, purged_at = ?
                    WHERE response_id IN ({placeholders}) AND purged_at IS NULL""",
                [stamp, *ids],
            )
            conn.execute(
                "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES ('last_retention_run', ?)",
                (f"{stamp} {reason} ids={len(ids)}",),
            )
        return len(ids)

    # -- reads -----------------------------------------------------------
    def find_request(self, fingerprint: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM generation_requests WHERE request_fingerprint = ? "
            "AND state = 'active'",
            (fingerprint,),
        ).fetchone()
        return dict(row) if row else None

    def get_candidate(self, candidate_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        return dict(row) if row else None

    def find_candidate_by_identity(
        self, candidate_hash: str, sense_key: str, target_language: str, variant_key: str | None
    ) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM candidates WHERE candidate_hash = ? AND sense_key = ? "
            "AND target_language = ? AND COALESCE(variant_key, 'base') = ?",
            (candidate_hash, sense_key, target_language, variant_key or "base"),
        ).fetchone()
        return dict(row) if row else None

    def count_candidates(self, batch_id: str | None = None, state: str | None = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM candidates WHERE 1=1"
        params: list[object] = []
        if batch_id is not None:
            sql += " AND batch_id = ?"
            params.append(batch_id)
        if state is not None:
            sql += " AND state = ?"
            params.append(state)
        return int(self._conn.execute(sql, params).fetchone()["n"])

    def count_requests(self, batch_id: str | None = None, state: str | None = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM generation_requests WHERE 1=1"
        params: list[object] = []
        if batch_id is not None:
            sql += " AND batch_id = ?"
            params.append(batch_id)
        if state is not None:
            sql += " AND state = ?"
            params.append(state)
        return int(self._conn.execute(sql, params).fetchone()["n"])

    def events_for(self, candidate_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM candidate_events WHERE candidate_id = ? ORDER BY event_id",
            (candidate_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def raw_responses_for(self, request_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM raw_responses WHERE request_id = ? ORDER BY response_id",
            (request_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def expired_raw_responses(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        rows = self._conn.execute(
            "SELECT response_id, request_id, retention_days, created_at FROM raw_responses "
            "WHERE purged_at IS NULL"
        ).fetchall()
        expired = []
        for row in rows:
            created = datetime.strptime(row["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if created + timedelta(days=int(row["retention_days"])) <= now:
                expired.append(dict(row))
        return expired

    def iter_candidates(self, state: str | None = None, batch_id: str | None = None) -> Iterable[dict]:
        sql = "SELECT * FROM candidates"
        clauses: list[str] = []
        params: list[object] = []
        if state is not None:
            clauses.append("state = ?")
            params.append(state)
        if batch_id is not None:
            clauses.append("batch_id = ?")
            params.append(batch_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY candidate_id"
        for row in self._conn.execute(sql, params):
            yield dict(row)


def quarantine_candidate(ledger: SqliteLedger, draft: CandidateDraft, result: ValidationResult, batch_id: str) -> dict:
    """Helper: the audit event written when a candidate fails validation."""
    return {
        "candidate_id": draft.candidate_id,
        "batch_id": batch_id,
        "actor": AGENT,
        "from_state": "generated",
        "to_state": "quarantined",
        "reason": f"{result.code}: {result.reason}",
        "at": utc_now(),
    }
