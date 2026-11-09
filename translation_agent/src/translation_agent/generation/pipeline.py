"""Generation pipeline: prompt -> provider -> parse -> validate -> ledger.

One batch is one transaction.  If anything raises mid-batch — provider
failure, parse failure beyond retries, duplicate candidate — nothing is
committed, including the audit rows collected so far.

Request identity is v2 (TASK 020): the *resolved input* (word, pinyin, gloss,
source revision, rendered prompt) is part of the fingerprint, so correcting a
source gloss produces a new request instead of silently reusing an old
candidate.  A ``variant_key`` lets an intentional second generation for the
same sense coexist with the first.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..audit.raw_response_store import prepare_response
from ..config import AgentConfig
from ..domain.identity import (
    NORMALIZATION_VERSION,
    REQUEST_FINGERPRINT_VERSION,
    candidate_hash,
    candidate_id as make_candidate_id,
    normalize_text,
    canonical_json,
    request_fingerprint_v1,
    request_fingerprint_v2,
    request_id as make_request_id,
    sha256_hex,
    source_revision_hash,
)
from ..domain.models import CandidateDraft, GenerationRequest, SenseRef
from ..ledger.sqlite_ledger import AGENT, SqliteLedger, utc_now
from ..providers.base import Provider, ProviderError
from ..providers.fake_provider import parse_translation
from ..validation.validator import validate_candidate


PROMPT_VERSION = "p1"
PROMPT_TEMPLATE = """You translate Chinese dictionary senses into Nepali.

Source word (simplified): {simplified}
Pinyin: {pinyin}
English gloss: {gloss_en}

Return JSON only: {{"translation": "<natural modern Nepali for this specific sense>",
"confidence": <0-1>}}.  Do not translate the headword; translate this sense.
"""


def build_prompt(sense: SenseRef) -> str:
    return PROMPT_TEMPLATE.format(
        simplified=sense.simplified, pinyin=sense.pinyin, gloss_en=sense.gloss_en
    )


def prompt_checksum() -> str:
    return sha256_hex(PROMPT_TEMPLATE)


def rendered_prompt_hash(sense: SenseRef) -> str:
    return sha256_hex(build_prompt(sense))


@dataclass
class BatchResult:
    batch_id: str
    processed: int = 0
    inserted: int = 0
    needs_review: int = 0
    quarantined: int = 0
    skipped_existing: int = 0
    failures: list[dict] = field(default_factory=list)


class TranslationPipeline:
    def __init__(self, ledger: SqliteLedger, provider: Provider, config: AgentConfig):
        self.ledger = ledger
        self.provider = provider
        self.config = config

    def _parameters(self) -> dict:
        """Resolved provider settings.  Fail loudly rather than fingerprinting None."""
        params = self.provider.parameters() if hasattr(self.provider, "parameters") else {}
        if not isinstance(params, dict):
            raise TypeError(f"provider {self.provider.name!r} returned non-dict parameters")
        return params

    def _request_for(self, sense: SenseRef, variant_key: str | None = None) -> GenerationRequest:
        revision = source_revision_hash(
            sense_key=sense.sense_key,
            simplified=sense.simplified,
            pinyin=sense.pinyin,
            gloss_en=sense.gloss_en,
        )
        rendered = rendered_prompt_hash(sense)
        fingerprint = request_fingerprint_v2(
            sense_key=sense.sense_key,
            source_word=sense.simplified,
            source_pinyin=sense.pinyin,
            source_gloss=sense.gloss_en,
            source_revision_hash=revision,
            target_language=self.config.target_language,
            provider=self.provider.name,
            model=self.provider.model,
            model_parameters=self._parameters(),
            prompt_version=PROMPT_VERSION,
            prompt_checksum=prompt_checksum(),
            rendered_prompt_sha256=rendered,
            variant_key=variant_key,
        )
        legacy = request_fingerprint_v1(
            sense_key=sense.sense_key,
            target_language=self.config.target_language,
            provider=self.provider.name,
            model=self.provider.model,
            prompt_version=PROMPT_VERSION,
            prompt_checksum=prompt_checksum(),
        )
        return GenerationRequest(
            request_id=make_request_id(fingerprint),
            sense_key=sense.sense_key,
            target_language=self.config.target_language,
            provider=self.provider.name,
            model=self.provider.model,
            prompt_version=PROMPT_VERSION,
            prompt_checksum=prompt_checksum(),
            request_fingerprint=fingerprint,
            request_fingerprint_v1=legacy,
            fingerprint_version=REQUEST_FINGERPRINT_VERSION,
            source_word=sense.simplified,
            source_pinyin=sense.pinyin,
            source_gloss=sense.gloss_en,
            source_revision_hash=revision,
            rendered_prompt_sha256=rendered,
            variant_key=variant_key,
            model_parameters=self._parameters(),
        )

    def run_batch(
        self,
        senses: list[SenseRef],
        batch_id: str,
        variant_key: str | None = None,
    ) -> BatchResult:
        requests: list[dict] = []
        drafts: list[CandidateDraft] = []
        events: list[dict] = []
        attempts: list[dict] = []
        raw_rows: list[dict] = []
        result = BatchResult(batch_id=batch_id)

        for sense in senses:
            result.processed += 1
            request = self._request_for(sense, variant_key)
            if self.ledger.find_request(request.request_fingerprint) is not None:
                result.skipped_existing += 1
                continue

            payload = None
            last_error: ProviderError | None = None
            for attempt_no in range(1, self.config.max_attempts + 1):
                try:
                    provider_result = self.provider.generate(request, sense)
                except ProviderError as exc:
                    last_error = exc
                    attempts.append(
                        {
                            "request_id": request.request_id,
                            "provider": self.provider.name,
                            "model": self.provider.model,
                            "attempt_no": attempt_no,
                            "status": "error",
                            "latency_ms": None,
                            "error_code": getattr(exc, "code", "provider_error"),
                            "created_at": utc_now(),
                        }
                    )
                    continue
                attempts.append(
                    {
                        "request_id": request.request_id,
                        "provider": self.provider.name,
                        "model": self.provider.model,
                        "attempt_no": attempt_no,
                        "status": "ok",
                        "latency_ms": provider_result.latency_ms,
                        "error_code": None,
                        "created_at": utc_now(),
                    }
                )
                payload = parse_translation(provider_result.raw)
                raw_rows.append(
                    prepare_response(
                        request_id=request.request_id,
                        payload=provider_result.raw,
                        max_bytes=self.config.raw_response_max_bytes,
                        retention_days=self.config.retention_days,
                    )
                )
                break

            if payload is None:
                result.failures.append(
                    {
                        "sense_key": sense.sense_key,
                        "error": getattr(last_error, "code", "provider_error"),
                        "message": str(last_error) if last_error else "no attempt succeeded",
                    }
                )
                message = (
                    f"batch {batch_id}: sense {sense.sense_key} exhausted "
                    f"{self.config.max_attempts} attempt(s); batch aborted, nothing written"
                )
                # Preserve the provider error class so callers can distinguish
                # timeout / invalid-json / upstream failure from a batch bug.
                if isinstance(last_error, ProviderError):
                    raise type(last_error)(message) from last_error
                raise ProviderError(message)

            original = payload["translation"]
            normalized = normalize_text(original, NORMALIZATION_VERSION)
            c_hash = candidate_hash(normalized, self.config.target_language, NORMALIZATION_VERSION)
            c_id = make_candidate_id(c_hash, variant_key)
            validation = validate_candidate(original, sense)

            if validation.ok:
                draft = CandidateDraft(
                    candidate_id=c_id,
                    request_id=request.request_id,
                    sense_key=sense.sense_key,
                    target_language=self.config.target_language,
                    original_text=original,
                    normalized_text=normalized,
                    normalization_version=NORMALIZATION_VERSION,
                    candidate_hash=c_hash,
                    variant_key=variant_key,
                    state="needs_review",
                )
                events.append(
                    {
                        "candidate_id": c_id,
                        "batch_id": batch_id,
                        "actor": AGENT,
                        "from_state": "generated",
                        "to_state": "validated",
                        "reason": "mechanical validation passed",
                        "at": utc_now(),
                    }
                )
                events.append(
                    {
                        "candidate_id": c_id,
                        "batch_id": batch_id,
                        "actor": AGENT,
                        "from_state": "validated",
                        "to_state": "needs_review",
                        "reason": "queued for human review",
                        "at": utc_now(),
                    }
                )
                result.needs_review += 1
            else:
                draft = CandidateDraft(
                    candidate_id=c_id,
                    request_id=request.request_id,
                    sense_key=sense.sense_key,
                    target_language=self.config.target_language,
                    original_text=original,
                    normalized_text=normalized,
                    normalization_version=NORMALIZATION_VERSION,
                    candidate_hash=c_hash,
                    variant_key=variant_key,
                    state="quarantined",
                )
                events.append(
                    {
                        "candidate_id": c_id,
                        "batch_id": batch_id,
                        "actor": AGENT,
                        "from_state": "generated",
                        "to_state": "quarantined",
                        "reason": f"{validation.code}: {validation.reason}",
                        "at": utc_now(),
                    }
                )
                result.quarantined += 1

            drafts.append(draft)
            requests.append(
                {
                    "request_id": request.request_id,
                    "batch_id": batch_id,
                    "sense_key": request.sense_key,
                    "target_language": request.target_language,
                    "provider": request.provider,
                    "model": request.model,
                    "prompt_version": request.prompt_version,
                    "prompt_checksum": request.prompt_checksum,
                    "request_fingerprint": request.request_fingerprint,
                    "request_fingerprint_v1": request.request_fingerprint_v1,
                    "fingerprint_version": request.fingerprint_version,
                    "variant_key": request.variant_key,
                    "source_word": request.source_word,
                    "source_pinyin": request.source_pinyin,
                    "source_gloss": request.source_gloss,
                    "source_revision_hash": request.source_revision_hash,
                    "rendered_prompt_sha256": request.rendered_prompt_sha256,
                    "model_parameters": canonical_json(request.model_parameters or {}),
                    "state": "active",
                    "created_at": utc_now(),
                }
            )

        # Candidates whose row already exists (same hash + sense) would violate
        # the uniqueness constraint; treat them as already-present, not as new
        # work, so a re-run stays idempotent.
        keep: list[CandidateDraft] = []
        for draft in drafts:
            existing = self.ledger.find_candidate_by_identity(
                draft.candidate_hash, draft.sense_key, draft.target_language, draft.variant_key
            )
            if existing is not None:
                result.skipped_existing += 1
                continue
            keep.append(draft)
        drafts = keep

        result.inserted = self.ledger.commit_batch(
            batch_id=batch_id,
            requests=requests,
            candidates=drafts,
            events=events,
            attempts=attempts,
            raw_responses=raw_rows,
        )
        return result


def describe(result: BatchResult) -> str:
    return json.dumps(
        {
            "batch_id": result.batch_id,
            "processed": result.processed,
            "inserted": result.inserted,
            "needs_review": result.needs_review,
            "quarantined": result.quarantined,
            "skipped_existing": result.skipped_existing,
            "failures": result.failures,
        },
        ensure_ascii=False,
        indent=2,
    )
