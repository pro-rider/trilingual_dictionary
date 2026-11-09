"""Retention: erase payloads, keep candidates and audit linkage."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from translation_agent.audit.retention import apply_retention, plan_retention
from translation_agent.config import AgentConfig
from translation_agent.domain.models import SenseRef
from translation_agent.generation.pipeline import TranslationPipeline
from translation_agent.ledger.sqlite_ledger import SqliteLedger
from translation_agent.providers.fake_provider import FakeProvider


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "senses" / "pilot_fixture.json"
SENSE = SenseRef("fixture:1001", 1001, "水", "shui3", "water")


def seed(tmp_path: Path, retention_days: int | str = 30) -> SqliteLedger:
    ledger = SqliteLedger(str(tmp_path / "c.db"))
    cfg = AgentConfig(ledger_path=ledger.path, retention_days=retention_days)
    TranslationPipeline(ledger, FakeProvider(), cfg).run_batch([SENSE], batch_id="b1")
    return ledger


def backdate(ledger: SqliteLedger, days: int) -> None:
    stamp = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger._conn.execute("UPDATE raw_responses SET created_at = ?", (stamp,))


def test_nothing_expires_immediately(tmp_path: Path):
    with seed(tmp_path) as ledger:
        assert plan_retention(ledger)["expired"] == 0


def test_plan_is_read_only(tmp_path: Path):
    with seed(tmp_path) as ledger:
        backdate(ledger, 60)
        plan = plan_retention(ledger)
        assert plan["expired"] == 1
        rows = ledger._conn.execute("SELECT payload, purged_at FROM raw_responses").fetchall()
        assert rows[0]["purged_at"] is None
        assert rows[0]["payload"] != "[PURGED]"


def test_apply_erases_payload_but_keeps_candidate_and_row(tmp_path: Path):
    with seed(tmp_path, retention_days="30") as ledger:
        backdate(ledger, 60)
        report = apply_retention(ledger)
        assert report["purged"] == 1
        row = ledger._conn.execute(
            "SELECT payload, bytes, purged_at, request_id FROM raw_responses"
        ).fetchone()
        assert row["payload"] == "[PURGED]"
        assert row["bytes"] == 0
        assert row["purged_at"] is not None
        assert ledger.count_candidates(batch_id="b1") == 1
        assert ledger.count_requests(batch_id="b1") == 1
        events = ledger._conn.execute("SELECT COUNT(*) AS n FROM candidate_events").fetchone()
        assert int(events["n"]) == 2
        meta = ledger._conn.execute(
            "SELECT value FROM ledger_meta WHERE key='last_retention_run'"
        ).fetchone()
        assert "retention" in meta["value"]


def test_retention_is_idempotent(tmp_path: Path):
    with seed(tmp_path) as ledger:
        backdate(ledger, 60)
        first = apply_retention(ledger)
        second = apply_retention(ledger)
        assert first["purged"] == 1
        assert second["purged"] == 0


def test_retention_does_not_touch_candidate_text(tmp_path: Path):
    with seed(tmp_path) as ledger:
        before = [row["original_text"] for row in ledger.iter_candidates()]
        backdate(ledger, 60)
        apply_retention(ledger)
        after = [row["original_text"] for row in ledger.iter_candidates()]
        assert before == after


def test_longer_retention_window_keeps_payload(tmp_path: Path):
    with seed(tmp_path, retention_days="365") as ledger:
        backdate(ledger, 60)
        assert plan_retention(ledger)["expired"] == 0
