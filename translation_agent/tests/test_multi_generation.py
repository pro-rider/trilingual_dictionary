"""Multiple generations for one sense: a variant is a new request, not an overwrite."""

from __future__ import annotations

from pathlib import Path

from translation_agent.config import AgentConfig
from translation_agent.domain.models import SenseRef
from translation_agent.generation.pipeline import TranslationPipeline
from translation_agent.ledger.sqlite_ledger import REVIEWER, SqliteLedger
from translation_agent.providers.fake_provider import FakeProvider


SENSE = SenseRef("fixture:1001", 1001, "水", "shui3", "water")


def test_variant_produces_a_second_request_and_candidate(tmp_path: Path):
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        first = pipeline.run_batch([SENSE], batch_id="b1")
        second = pipeline.run_batch([SENSE], batch_id="b1-alt", variant_key="alt")
        assert first.inserted == 1 and second.inserted == 1
        assert ledger.count_requests() == 2
        rows = list(ledger.iter_candidates())
        variants = sorted((row["variant_key"] or "base") for row in rows)
        assert variants == ["alt", "base"]
        request_variants = [
            row["variant_key"] for row in ledger._conn.execute("SELECT variant_key FROM generation_requests")
        ]
        assert sorted(v or "base" for v in request_variants) == ["alt", "base"]


def test_a_rejected_candidate_stays_recoverable(tmp_path: Path):
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        TranslationPipeline(ledger, FakeProvider(), cfg).run_batch([SENSE], batch_id="b1")
        candidate = next(iter(ledger.iter_candidates()))
        ledger.transition(candidate["candidate_id"], "rejected", REVIEWER, "wrong sense")
        row = ledger.get_candidate(candidate["candidate_id"])
        assert row is not None
        assert row["state"] == "rejected"
        assert row["original_text"] == candidate["original_text"]
        events = ledger.events_for(candidate["candidate_id"])
        assert events[-1]["to_state"] == "rejected"
        # A reviewer can send it back to review; the payload was never lost.
        assert ledger.transition(candidate["candidate_id"], "needs_review", REVIEWER, "reconsider") == "needs_review"


def test_corrected_gloss_triggers_a_new_request(tmp_path: Path):
    """The v1 defect, end to end: same sense, corrected gloss, must not be skipped."""
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        first = pipeline.run_batch([SENSE], batch_id="b1")
        assert first.inserted == 1
        corrected = SenseRef(SENSE.sense_key, SENSE.entry_id, SENSE.simplified, SENSE.pinyin, "body of water")
        second = pipeline.run_batch([corrected], batch_id="b2")
        # A NEW request is recorded (that is the v1 fix).  The provider is
        # deterministic on the sense key, so the produced text is identical and
        # the candidate is deduplicated rather than duplicated.
        assert second.skipped_existing == 1
        assert ledger.count_requests() == 2
        assert ledger.count_candidates() == 1
        latest = ledger._conn.execute(
            "SELECT source_gloss, request_fingerprint FROM generation_requests "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        assert latest["source_gloss"] == "body of water"
        assert ledger.count_requests(state="active") == 2
        stored = ledger._conn.execute(
            "SELECT source_gloss FROM generation_requests ORDER BY created_at"
        ).fetchall()
        assert {row["source_gloss"] for row in stored} == {"water", "body of water"}


def test_identical_text_in_the_same_variant_is_deduplicated(tmp_path: Path):
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        pipeline.run_batch([SENSE], batch_id="b1")
        # A different batch under the same variant with identical text is a
        # duplicate of the candidate, not new work — even though the request id
        # differs because the batch id does not participate in the fingerprint.
        again = pipeline.run_batch([SENSE], batch_id="b2")
        assert again.skipped_existing == 1
        assert ledger.count_candidates() == 1
        assert ledger.count_requests() == 1


def test_a_variant_may_repeat_the_text_of_the_base_candidate(tmp_path: Path):
    """An intentional second generation keeps its own row even with equal text."""
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        pipeline.run_batch([SENSE], batch_id="b1")
        again = pipeline.run_batch([SENSE], batch_id="b2", variant_key="alt")
        assert again.inserted == 1
        assert ledger.count_candidates() == 2
        assert ledger.count_requests() == 2
