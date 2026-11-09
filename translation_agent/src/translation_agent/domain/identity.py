"""Candidate identity: normalization, canonical serialisation, hashes.

Deliberately distinct from the production ``content_fingerprint`` (v1) which
hashes database contents.  These are *candidate* identities: they identify
normalized text and generation requests, never linguistic equivalence.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata


FINGERPRINT_VERSION = 1
NORMALIZATION_VERSION = "nfc-ws1-v1"
SUPPORTED_NORMALIZATIONS = (NORMALIZATION_VERSION,)

_WS_RUN = re.compile(r"[\s\u00a0\u200b]+")


def normalize_text(text: str, version: str = NORMALIZATION_VERSION) -> str:
    """NFC + deterministic whitespace collapse.  Nothing else is touched.

    Case, punctuation and diacritics are preserved on purpose: in Chinese
    and Nepali they carry meaning.  NFKC is *not* applied.
    """
    if version not in SUPPORTED_NORMALIZATIONS:
        raise ValueError(f"unsupported normalization version: {version!r}")
    if not isinstance(text, str):
        raise TypeError("text must be str")
    normalized = unicodedata.normalize("NFC", text)
    return _WS_RUN.sub(" ", normalized).strip()


def canonical_json(obj: object) -> str:
    """Frozen serialisation for every hash in this subsystem."""
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_hex(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def candidate_hash(
    normalized_text: str,
    target_language: str,
    normalization_version: str = NORMALIZATION_VERSION,
) -> str:
    payload = {
        "fingerprint_version": FINGERPRINT_VERSION,
        "normalization_version": normalization_version,
        "target_language": target_language,
        "text": normalized_text,
    }
    return sha256_hex(canonical_json(payload))


def request_fingerprint(
    *,
    sense_key: str,
    target_language: str,
    provider: str,
    model: str,
    prompt_version: str,
    prompt_checksum: str,
) -> str:
    payload = {
        "fingerprint_version": FINGERPRINT_VERSION,
        "sense_key": sense_key,
        "target_language": target_language,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "prompt_checksum": prompt_checksum,
    }
    return sha256_hex(canonical_json(payload))


def candidate_id(c_text_hash: str, variant_key: str | None = None) -> str:
    tail = "base" if variant_key is None else f"v-{variant_key}"
    return f"cand_{c_text_hash[:24]}_{tail}"


def request_id(fingerprint: str) -> str:
    return f"req_{fingerprint[:24]}"


# ---------------------------------------------------------------------------
# Request identity, version 2 (TASK 020)
#
# v1 identified the *configuration* (sense key + model + prompt), not the
# *input*.  A corrected gloss under the same prompt produced the same v1
# fingerprint, so a stale candidate could be silently reused.  v2 hashes the
# whole resolved generation input.  v1 is kept verbatim and never recomputed:
# stored v1 values stay valid historical values.
# ---------------------------------------------------------------------------

REQUEST_FINGERPRINT_VERSION = 2
OUTPUT_SCHEMA_VERSION = "candidate-json-v1"


def request_fingerprint_v1(
    *,
    sense_key: str,
    target_language: str,
    provider: str,
    model: str,
    prompt_version: str,
    prompt_checksum: str,
) -> str:
    """Frozen v1 algorithm.  Do not change: stored values depend on it."""
    payload = {
        "fingerprint_version": FINGERPRINT_VERSION,
        "sense_key": sense_key,
        "target_language": target_language,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "prompt_checksum": prompt_checksum,
    }
    return sha256_hex(canonical_json(payload))


request_fingerprint = request_fingerprint_v1


def source_revision_hash(
    *,
    sense_key: str,
    simplified: str,
    pinyin: str,
    gloss_en: str,
    normalization_version: str = NORMALIZATION_VERSION,
) -> str:
    """Identity of the source sense *as resolved for this run*."""
    payload = {
        "fingerprint_version": REQUEST_FINGERPRINT_VERSION,
        "normalization_version": normalization_version,
        "sense_key": sense_key,
        "simplified": normalize_text(simplified, normalization_version),
        "pinyin": normalize_text(pinyin, normalization_version),
        "gloss_en": normalize_text(gloss_en, normalization_version),
    }
    return sha256_hex(canonical_json(payload))


def request_fingerprint_v2(
    *,
    sense_key: str,
    source_word: str,
    source_pinyin: str,
    source_gloss: str,
    source_revision_hash: str,
    target_language: str,
    provider: str,
    model: str,
    model_parameters: dict | None,
    prompt_version: str,
    prompt_checksum: str,
    rendered_prompt_sha256: str,
    output_schema_version: str = OUTPUT_SCHEMA_VERSION,
    variant_key: str | None = None,
    normalization_version: str = NORMALIZATION_VERSION,
) -> str:
    payload = {
        "fingerprint_version": REQUEST_FINGERPRINT_VERSION,
        "normalization_version": normalization_version,
        "sense_key": sense_key,
        "source_word": normalize_text(source_word, normalization_version),
        "source_pinyin": normalize_text(source_pinyin, normalization_version),
        "source_gloss": normalize_text(source_gloss, normalization_version),
        "source_revision_hash": source_revision_hash,
        "target_language": target_language,
        "provider": provider,
        "model": model,
        "model_parameters": model_parameters or {},
        "prompt_version": prompt_version,
        "prompt_checksum": prompt_checksum,
        "rendered_prompt_sha256": rendered_prompt_sha256,
        "output_schema_version": output_schema_version,
        "variant_key": variant_key,
    }
    return sha256_hex(canonical_json(payload))
