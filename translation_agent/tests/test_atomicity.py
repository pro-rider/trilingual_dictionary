"""Batch atomicity: a failure mid-batch leaves zero rows of any kind."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from translation_agent.config import AgentConfig
from translation_agent.domain.models import SenseRef
from translation_agent.generation.pipeline import TranslationPipeline
from translation_agent.ledger.sqlite_ledger import SqliteLedger
from translation_agent.providers.base import ProviderFailure
from translation_agent.providers.fake_provider import FakeProvider, RaisingProvider


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "senses" / "pilot_fixture.json"


def senses(n: int = 4) -> list[SenseRef]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [
        SenseRef(
            sense_key=item["sense_key"],
            entry_id=item["entry_id"],
            simplified=item["simplified"],
            pinyin=item["pinyin"],
            gloss_en=item["gloss_en"],
        )
        for item in data["senses"][:n]
    ]


def fresh_ledger(tmp_path: Path) -> SqliteLedger:
    return SqliteLedger(str(tmp_path / "candidates.db"))


def test_happy_batch_commits_everything(tmp_path):
    with fresh_ledger(tmp_path) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        result = pipeline.run_batch(senses(4), batch_id="b-happy")
        assert result.inserted == 4
        assert result.quarantined == 0
        assert ledger.count_candidates("b-happy") == 4
        assert ledger.count_requests("b-happy") == 4


def test_failure_after_two_calls_leaves_no_rows(tmp_path):
    with fresh_ledger(tmp_path) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path, max_attempts=1)
        pipeline = TranslationPipeline(ledger, RaisingProvider(fail_after=2), cfg)
        with pytest.raises(ProviderFailure):
            pipeline.run_batch(senses(4), batch_id="b-fail")
        assert ledger.count_candidates() == 0
        assert ledger.count_requests() == 0
        # attempts are also part of the same transaction: nothing survives
        rows = ledger._conn.execute("SELECT COUNT(*) AS n FROM provider_attempts").fetchone()
        assert int(rows["n"]) == 0


def test_quarantined_candidate_is_stored_but_not_reviewable(tmp_path):
    with fresh_ledger(tmp_path) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        provider = FakeProvider(behaviours={"fixture:1001": "latin"})
        pipeline = TranslationPipeline(ledger, provider, cfg)
        result = pipeline.run_batch(senses(3), batch_id="b-mixed")
        assert result.quarantined == 1
        assert ledger.count_candidates("b-mixed", state="quarantined") == 1
        assert ledger.count_candidates("b-mixed", state="needs_review") == 2


def test_rollback_batch_retires_rows_and_keeps_all_evidence(tmp_path):
    """CONTRACT CHANGE (TASK 020): rollback no longer deletes.

    The payload, provenance, candidate id and lifecycle events all survive; the
    row is retired into ``rolled_back``.  Deleting them disconnected the audit
    event from the thing it described.
    """
    with fresh_ledger(tmp_path) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        pipeline.run_batch(senses(3), batch_id="b-roll")
        assert ledger.count_candidates("b-roll") == 3
        retired = ledger.rollback_batch("b-roll")
        assert retired == 3
        assert ledger.count_candidates("b-roll") == 3
        assert ledger.count_candidates("b-roll", state="rolled_back") == 3
        assert ledger.count_requests("b-roll", state="rolled_back") == 3
        for row in ledger.iter_candidates(batch_id="b-roll"):
            assert row["state"] == "rolled_back"
            assert row["original_text"], "payload must survive rollback"
            assert row["request_id"], "request linkage must survive rollback"
        events = ledger._conn.execute(
            "SELECT to_state, COUNT(*) AS n FROM candidate_events WHERE batch_id = ? GROUP BY to_state",
            ("b-roll",),
        ).fetchall()
        states = {row["to_state"]: int(row["n"]) for row in events}
        assert states.get("rolled_back") == 3
        assert states.get("needs_review") == 3


def test_failed_batch_leaves_no_attempt_rows_and_reports_redacted_errors(tmp_path):
    """Decided contract (TASK 021): a failed batch is all-or-nothing.

    Nothing persists — including provider attempts — so a retry cannot observe
    half-written history.  The evidence is the raised provider error, which
    preserves the error class and must never carry a secret.
    """
    import json as _json

    import pytest as _pytest

    from translation_agent.providers.base import ProviderError
    from translation_agent.providers.fake_provider import RaisingProvider

    with fresh_ledger(tmp_path) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, RaisingProvider(fail_after=2), cfg)
        with _pytest.raises(ProviderError) as excinfo:
            pipeline.run_batch(senses(4), batch_id="b-fail")
        assert type(excinfo.value).__name__ == "ProviderFailure"
        blob = str(excinfo.value).lower()
        assert "sk-" not in blob and "api_key" not in blob and "bearer" not in blob
        assert "fixture:1003" in str(excinfo.value), "the failing sense must be named"
        for table in ("candidates", "generation_requests", "provider_attempts", "raw_responses"):
            count = ledger._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            assert int(count) == 0, f"{table} must be empty after a failed batch"
