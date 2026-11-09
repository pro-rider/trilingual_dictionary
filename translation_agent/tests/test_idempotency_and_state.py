"""Idempotency and state-machine ownership.

Re-running a batch must not duplicate work; and no actor except a human
reviewer may approve — the generation agent cannot promote its own output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from translation_agent.config import AgentConfig
from translation_agent.domain.models import SenseRef
from translation_agent.generation.pipeline import TranslationPipeline
from translation_agent.ledger.sqlite_ledger import (
    AGENT,
    IMPORTER,
    REVIEWER,
    SqliteLedger,
    StateTransitionRefused,
)
from translation_agent.providers.fake_provider import FakeProvider


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "senses" / "pilot_fixture.json"


def senses(n: int) -> list[SenseRef]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [
        SenseRef(
            sense_key=i["sense_key"],
            entry_id=i["entry_id"],
            simplified=i["simplified"],
            pinyin=i["pinyin"],
            gloss_en=i["gloss_en"],
        )
        for i in data["senses"][:n]
    ]


def test_second_run_is_a_no_op(tmp_path):
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        first = pipeline.run_batch(senses(3), batch_id="b1")
        assert first.inserted == 3
        second = pipeline.run_batch(senses(3), batch_id="b2")
        assert second.inserted == 0
        assert second.skipped_existing == 3
        assert ledger.count_candidates() == 3
        assert ledger.count_requests() == 3


def test_agent_cannot_approve_or_import(tmp_path):
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        result = pipeline.run_batch(senses(1), batch_id="b1")
        assert result.inserted == 1
        candidate = next(iter(ledger.iter_candidates(state="needs_review")))

        with pytest.raises(StateTransitionRefused):
            ledger.transition(candidate["candidate_id"], "approved", AGENT, "self-approval attempt")
        with pytest.raises(StateTransitionRefused):
            ledger.transition(candidate["candidate_id"], "approved", IMPORTER, "wrong actor")

        # Only a human reviewer may approve.
        assert ledger.transition(candidate["candidate_id"], "approved", REVIEWER, "reviewed") == "approved"
        # Only the parent importer may import, and only from approved.
        assert ledger.transition(candidate["candidate_id"], "imported", IMPORTER, "parent import") == "imported"
        with pytest.raises(StateTransitionRefused):
            ledger.transition(candidate["candidate_id"], "needs_review", AGENT, "rewind after import")


def test_unknown_state_is_refused(tmp_path):
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        pipeline.run_batch(senses(1), batch_id="b1")
        candidate = next(iter(ledger.iter_candidates()))
        with pytest.raises(StateTransitionRefused):
            ledger.transition(candidate["candidate_id"], "human_verified", REVIEWER, "not a state")


def test_events_record_actor_and_reason(tmp_path):
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        pipeline.run_batch(senses(1), batch_id="b1")
        candidate = next(iter(ledger.iter_candidates()))
        events = ledger.events_for(candidate["candidate_id"])
        assert [e["to_state"] for e in events] == ["validated", "needs_review"]
        assert all(e["actor"] == AGENT for e in events)
