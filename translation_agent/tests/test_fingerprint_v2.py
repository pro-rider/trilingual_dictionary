"""Request identity v2: the resolved input is part of the fingerprint.

The defect this closes: with v1, correcting a source gloss kept the same
fingerprint, so the pipeline skipped the corrected sense and reused a stale
candidate.
"""

from __future__ import annotations

from translation_agent.config import AgentConfig
from translation_agent.domain.identity import (
    NORMALIZATION_VERSION,
    REQUEST_FINGERPRINT_VERSION,
    canonical_json,
    request_fingerprint_v1,
    request_fingerprint_v2,
    sha256_hex,
    source_revision_hash,
)
from translation_agent.domain.models import SenseRef
from translation_agent.generation.pipeline import TranslationPipeline
from translation_agent.ledger.sqlite_ledger import SqliteLedger
from translation_agent.providers.fake_provider import FakeProvider

BASE = dict(
    sense_key="fixture:1001",
    source_word="水",
    source_pinyin="shui3",
    source_gloss="water",
    target_language="ne",
    provider="fake",
    model="fake-v1",
    model_parameters=None,
    prompt_version="p1",
    prompt_checksum="checksum-1",
    rendered_prompt_sha256="rendered-1",
)


def fp(**overrides) -> str:
    kwargs = dict(BASE)
    kwargs.update(overrides)
    kwargs["source_revision_hash"] = source_revision_hash(
        sense_key=kwargs["sense_key"],
        simplified=kwargs["source_word"],
        pinyin=kwargs["source_pinyin"],
        gloss_en=kwargs["source_gloss"],
    )
    return request_fingerprint_v2(**kwargs)


def test_v2_is_stable_for_identical_input():
    assert fp() == fp()


def test_v2_changes_when_the_gloss_is_corrected():
    assert fp(source_gloss="water") != fp(source_gloss="body of water")


def test_v2_changes_when_the_word_or_pinyin_changes():
    assert fp(source_word="水") != fp(source_word="河水")
    assert fp(source_pinyin="shui3") != fp(source_pinyin="shui4")


def test_v2_changes_when_the_rendered_prompt_changes():
    assert fp(rendered_prompt_sha256="a") != fp(rendered_prompt_sha256="b")


def test_v2_changes_with_model_parameters_and_variant():
    assert fp(model_parameters={"temperature": 0.7}) != fp(model_parameters={"temperature": 0.2})
    assert fp() != fp(variant_key="alt")


def test_v1_stays_frozen_and_independent_of_the_source():
    """Stored v1 values must never drift, even when the gloss changes."""
    v1 = request_fingerprint_v1(
        sense_key="fixture:1001",
        target_language="ne",
        provider="fake",
        model="fake-v1",
        prompt_version="p1",
        prompt_checksum="checksum-1",
    )
    assert v1 == request_fingerprint_v1(
        sense_key="fixture:1001",
        target_language="ne",
        provider="fake",
        model="fake-v1",
        prompt_version="p1",
        prompt_checksum="checksum-1",
    )
    assert v1 != fp()


def test_golden_values_are_recorded_verbatim():
    """Literal values: a change here is an identity change, not a refactor."""
    assert REQUEST_FINGERPRINT_VERSION == 2
    revision = source_revision_hash(
        sense_key="fixture:1001", simplified="水", pinyin="shui3", gloss_en="water"
    )
    assert revision == sha256_hex(
        canonical_json(
            {
                "fingerprint_version": 2,
                "normalization_version": NORMALIZATION_VERSION,
                "sense_key": "fixture:1001",
                "simplified": "水",
                "pinyin": "shui3",
                "gloss_en": "water",
            }
        )
    )
    assert fp() == request_fingerprint_v2(**{**BASE, "source_revision_hash": revision})


class KnobProvider(FakeProvider):
    """Same text, different resolved settings — identity must notice."""

    def __init__(self, temperature: float) -> None:
        super().__init__()
        self._temperature = temperature

    def parameters(self) -> dict:
        params = super().parameters()
        params["temperature"] = self._temperature
        return params


def test_changing_a_generation_parameter_changes_the_request(tmp_path):
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        cold = TranslationPipeline(ledger, KnobProvider(0.0), cfg)
        warm = TranslationPipeline(ledger, KnobProvider(0.7), cfg)
        cold.run_batch([SenseRef('fixture:1001', 1001, '水', 'shui3', 'water')], batch_id="cold")
        warm.run_batch([SenseRef('fixture:1001', 1001, '水', 'shui3', 'water')], batch_id="warm")
        assert ledger.count_requests() == 2, "parameters are identity, not metadata"
        rows = ledger._conn.execute(
            "SELECT request_fingerprint, model_parameters FROM generation_requests"
        ).fetchall()
        fingerprints = {row["request_fingerprint"] for row in rows}
        assert len(fingerprints) == 2
        parameters = {row["model_parameters"] for row in rows}
        stored = " ".join(parameters)
        assert '"temperature":0.0' in stored and '"temperature":0.7' in stored
