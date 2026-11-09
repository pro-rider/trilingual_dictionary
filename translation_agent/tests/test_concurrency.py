"""Concurrency: bounded retry on BUSY, never an unbounded wait, never a retry
that re-runs a provider call."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from translation_agent.ledger.sqlite_ledger import LedgerBusy, SqliteLedger


def hold_lock(path: str, seconds: float, started: threading.Event, release: threading.Event) -> None:
    conn = sqlite3.connect(path, timeout=0.0, isolation_level=None)
    conn.execute("BEGIN IMMEDIATE")
    started.set()
    release.wait(timeout=seconds * 5)
    conn.execute("COMMIT")
    conn.close()


def test_writer_retries_while_another_writer_holds_the_lock(tmp_path: Path):
    path = str(tmp_path / "c.db")
    ledger = SqliteLedger(path, busy_retries=6, busy_backoff_ms=25)
    started, release = threading.Event(), threading.Event()
    thread = threading.Thread(target=hold_lock, args=(path, 0.15, started, release))
    thread.start()
    assert started.wait(timeout=2.0), "helper never acquired the lock"
    # A second writer must wait for the lock instead of failing immediately.
    with ledger.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES ('race', 'won')"
        )
    row = ledger._conn.execute("SELECT value FROM ledger_meta WHERE key='race'").fetchone()
    assert row["value"] == "won"
    release.set()
    thread.join(timeout=2.0)
    ledger.close()


def test_retry_budget_is_bounded_and_fails_loudly(tmp_path: Path):
    path = str(tmp_path / "c.db")
    ledger = SqliteLedger(path, busy_retries=2, busy_backoff_ms=10)
    started, release = threading.Event(), threading.Event()
    thread = threading.Thread(target=hold_lock, args=(path, 2.0, started, release))
    thread.start()
    assert started.wait(timeout=2.0)
    try:
        with pytest.raises(LedgerBusy):
            with ledger.transaction():
                pass
    finally:
        release.set()
        thread.join(timeout=3.0)
        ledger.close()


def test_retry_does_not_happen_for_non_lock_errors(tmp_path: Path):
    ledger = SqliteLedger(str(tmp_path / "c.db"))
    try:
        with pytest.raises(sqlite3.OperationalError):
            with ledger.transaction() as conn:
                conn.execute("SELECT * FROM table_that_does_not_exist")
    finally:
        ledger.close()


def test_transaction_rolls_back_cleanly_after_failure(tmp_path: Path):
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        with pytest.raises(RuntimeError):
            with ledger.transaction() as conn:
                conn.execute("INSERT OR REPLACE INTO ledger_meta(key, value) VALUES ('k', 'v')")
                raise RuntimeError("boom")
        assert (
            ledger._conn.execute("SELECT COUNT(*) AS n FROM ledger_meta WHERE key='k'").fetchone()["n"]
            == 0
        )
