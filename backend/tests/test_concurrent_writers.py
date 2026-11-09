"""Concurrency decision, exercised rather than described.

Decision: the store is **single-writer**. A write is opened with
``BEGIN IMMEDIATE``; a second writer is rejected with ``SQLITE_BUSY`` rather
than silently queued or allowed to interleave. Callers see an exception, and
the store keeps its previous content — never a half-written batch.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

from app.translations import schema  # noqa: E402
import import_legacy_ne as legacy  # noqa: E402


def _fresh_store(tmp_path):
    store = str(tmp_path / schema.DB_FILENAME)
    schema.migrate(store)
    return store


def _hold_write_lock(store, started, release):
    conn = sqlite3.connect(store, isolation_level=None)
    conn.execute("BEGIN IMMEDIATE")
    started.set()
    release.wait(3)
    conn.execute("ROLLBACK")
    conn.close()


def test_second_writer_is_rejected_not_serialised(tmp_path):
    store = _fresh_store(tmp_path)
    started, release = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold_write_lock, args=(store, started, release))
    holder.start()
    assert started.wait(3)

    try:
        conn = sqlite3.connect(store, isolation_level=None, timeout=0)
        with pytest.raises(sqlite3.OperationalError) as exc:
            conn.execute("BEGIN IMMEDIATE")
        assert "locked" in str(exc.value).lower()
        conn.close()
    finally:
        release.set()
        holder.join(5)


def test_a_locked_store_makes_the_import_fail_without_writing(tmp_path):
    store = _fresh_store(tmp_path)
    started, release = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold_write_lock, args=(store, started, release))
    holder.start()
    assert started.wait(3)

    rows = [{
        "translation_id": None, "sense_key": "水|shui3|water", "entry_key": "水|shui3",
        "language": "ne", "text": "पानी", "generation_method": "llm",
        "evidence_strength": "none", "validation_status": "incomplete",
        "publication_status": "labeled", "human_verification": "not_verified",
        "origin_source": "dictionary.sqlite:senses.ne", "origin_record_id": "1",
        "origin_retrieved_at": None, "origin_method": "legacy_ai_import",
        "origin_source_version": "dv", "legacy_status": None, "import_batch": None,
    }]

    try:
        with pytest.raises(sqlite3.OperationalError):
            legacy.apply(rows, store, "dv", "locked-batch")
    finally:
        release.set()
        holder.join(5)

    conn = schema.connect(store)
    try:
        assert conn.execute("select count(*) from translations").fetchone()[0] == 0
        assert conn.execute("select count(*) from event_log").fetchone()[0] == 0
    finally:
        conn.close()
