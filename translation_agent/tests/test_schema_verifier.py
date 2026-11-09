"""Schema verification must fail closed on structure, not just table names.

A file can contain every expected table and still be wrong.  Every test here
tampers with a real ledger file and asserts the mismatch is detected — and that
nothing is repaired.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from translation_agent.ledger.schema import (
    CONTRACT_VERSION,
    LEDGER_SCHEMA_VERSION,
    SCHEMA_STATEMENTS,
)
from translation_agent.ledger.schema_verifier import LedgerSchemaMismatch, introspect
from translation_agent.ledger.sqlite_ledger import LedgerError, SqliteLedger


def fresh(tmp_path: Path) -> Path:
    path = tmp_path / "candidates.db"
    SqliteLedger(str(path)).close()
    return path


def test_a_healthy_ledger_verifies(tmp_path: Path):
    with SqliteLedger(str(fresh(tmp_path)), create=False) as ledger:
        meta = ledger.verify_schema()
    assert meta["schema_version"] == LEDGER_SCHEMA_VERSION
    assert meta["contract_version"] == CONTRACT_VERSION
    assert len(meta["schema_fingerprint"]) == 64


def test_extra_column_is_detected(tmp_path: Path):
    path = fresh(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute("ALTER TABLE candidates ADD COLUMN sneaky TEXT")
    conn.commit()
    conn.close()
    with pytest.raises(LedgerSchemaMismatch) as excinfo:
        SqliteLedger(str(path), create=False)
    assert "candidates.columns" in str(excinfo.value)


def test_missing_index_is_detected(tmp_path: Path):
    path = fresh(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute("DROP INDEX idx_candidates_state")
    conn.commit()
    conn.close()
    with pytest.raises(LedgerSchemaMismatch) as excinfo:
        SqliteLedger(str(path), create=False)
    assert "idx_candidates_state" in str(excinfo.value)


def test_missing_table_is_detected(tmp_path: Path):
    path = fresh(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute("DROP TABLE raw_responses")
    conn.commit()
    conn.close()
    with pytest.raises(LedgerSchemaMismatch) as excinfo:
        SqliteLedger(str(path), create=False)
    assert "missing tables" in str(excinfo.value)


def test_missing_unique_constraint_is_detected(tmp_path: Path):
    """The exact case the old table-name check could not see."""
    path = fresh(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute("DROP INDEX idx_candidates_identity")
    conn.commit()
    conn.close()
    with pytest.raises(LedgerSchemaMismatch) as excinfo:
        SqliteLedger(str(path), create=False)
    assert "candidates.indexes" in str(excinfo.value)


def test_wrong_column_type_is_detected(tmp_path: Path):
    path = tmp_path / "wrong-type.db"
    conn = sqlite3.connect(str(path))
    for statement in SCHEMA_STATEMENTS:
        if "CREATE TABLE IF NOT EXISTS candidates" in statement:
            statement = statement.replace("original_text TEXT NOT NULL", "original_text BLOB")
        conn.execute(statement)
    conn.execute("INSERT INTO ledger_meta(key, value) VALUES ('schema_version', ?)", (LEDGER_SCHEMA_VERSION,))
    conn.execute("INSERT INTO ledger_meta(key, value) VALUES ('contract_version', ?)", (CONTRACT_VERSION,))
    conn.commit()
    conn.close()
    with pytest.raises(LedgerSchemaMismatch):
        SqliteLedger(str(path), create=False)


def test_verification_never_repairs(tmp_path: Path):
    path = fresh(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute("DROP INDEX idx_events_batch")
    conn.commit()
    conn.close()
    with pytest.raises(LedgerSchemaMismatch):
        SqliteLedger(str(path), create=False)
    # Still missing afterwards: verification is read-only.
    conn = sqlite3.connect(str(path))
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()
    assert "idx_events_batch" not in names


def test_legacy_version_is_refused(tmp_path: Path):
    path = fresh(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute("UPDATE ledger_meta SET value='1' WHERE key='schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(LedgerSchemaMismatch) as excinfo:
        SqliteLedger(str(path), create=False)
    assert "schema_version" in str(excinfo.value)


def test_introspection_reports_columns_and_indexes(tmp_path: Path):
    path = fresh(tmp_path)
    conn = sqlite3.connect(str(path))
    try:
        description = introspect(conn)
    finally:
        conn.close()
    column_names = [c["name"] for c in description["generation_requests"]["columns"]]
    assert "source_revision_hash" in column_names
    assert "request_fingerprint_v1" in column_names


def _rebuild_index(path: Path, name: str, create_sql: str) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(f'DROP INDEX "{name}"')
    conn.execute(create_sql)
    conn.commit()
    conn.close()


def test_changed_index_expression_is_detected(tmp_path: Path):
    """index_info() reports NULL for an expression column — only DDL sees it."""
    path = fresh(tmp_path)
    _rebuild_index(
        path,
        "idx_candidates_identity",
        "CREATE UNIQUE INDEX idx_candidates_identity ON candidates("
        "candidate_hash, sense_key, target_language, COALESCE(variant_key, variant_key || 'x'))",
    )
    with pytest.raises(LedgerSchemaMismatch) as excinfo:
        SqliteLedger(str(path), create=False)
    assert "candidates.indexes" in str(excinfo.value)


def test_changed_collation_is_detected(tmp_path: Path):
    path = fresh(tmp_path)
    _rebuild_index(
        path,
        "idx_candidates_batch",
        "CREATE INDEX idx_candidates_batch ON candidates(batch_id COLLATE NOCASE)",
    )
    with pytest.raises(LedgerSchemaMismatch):
        SqliteLedger(str(path), create=False)


def test_changed_sort_order_is_detected(tmp_path: Path):
    path = fresh(tmp_path)
    _rebuild_index(
        path,
        "idx_candidates_state",
        "CREATE INDEX idx_candidates_state ON candidates(state DESC)",
    )
    with pytest.raises(LedgerSchemaMismatch):
        SqliteLedger(str(path), create=False)


def test_partial_index_predicate_is_detected(tmp_path: Path):
    path = fresh(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute("DROP INDEX idx_candidates_batch")
    conn.execute(
        "CREATE INDEX idx_candidates_batch ON candidates(batch_id) WHERE state = 'approved'"
    )
    conn.commit()
    conn.close()
    with pytest.raises(LedgerSchemaMismatch):
        SqliteLedger(str(path), create=False)
