"""Domain value objects.  Frozen dataclasses: no hidden mutation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SenseRef:
    """A source sense.  ``sense_key`` is the stable production identity."""

    sense_key: str
    entry_id: int
    simplified: str
    pinyin: str
    gloss_en: str


@dataclass(frozen=True)
class GenerationRequest:
    request_id: str
    sense_key: str
    target_language: str
    provider: str
    model: str
    prompt_version: str
    prompt_checksum: str
    request_fingerprint: str
    # v2 (TASK 020): the resolved input is part of the identity
    request_fingerprint_v1: str = ""
    fingerprint_version: int = 2
    source_word: str = ""
    source_pinyin: str = ""
    source_gloss: str = ""
    source_revision_hash: str = ""
    rendered_prompt_sha256: str = ""
    variant_key: str | None = None
    # v2.1 (TASK 021): resolved provider settings are identity, not metadata
    model_parameters: dict | None = None


@dataclass(frozen=True)
class CandidateDraft:
    candidate_id: str
    request_id: str
    sense_key: str
    target_language: str
    original_text: str
    normalized_text: str
    normalization_version: str
    candidate_hash: str
    variant_key: str | None
    state: str


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    code: str
    reason: str

    @classmethod
    def passed(cls) -> "ValidationResult":
        return cls(True, "ok", "")

    @classmethod
    def failed(cls, code: str, reason: str) -> "ValidationResult":
        return cls(False, code, reason)

    def __bool__(self) -> bool:  # convenience, never use bare assert on it
        return self.ok


@dataclass(frozen=True)
class ProviderResult:
    raw: str
    attempt: int
    latency_ms: int
