"""Identity contract: normalization is conservative, hashes are versioned."""

from __future__ import annotations

import pytest

from translation_agent.domain.identity import (
    FINGERPRINT_VERSION,
    NORMALIZATION_VERSION,
    candidate_hash,
    candidate_id,
    normalize_text,
    request_fingerprint,
)


def test_nfc_is_applied():
    # decomposed e + combining acute must fold to the precomposed character
    assert normalize_text("e\u0301") == "\u00e9"


def test_nfkc_is_not_applied():
    # Full-width Latin stays full-width: NFKC would fold it to ASCII.
    assert normalize_text("ＡＢＣ") == "ＡＢＣ"


def test_case_and_punctuation_and_diacritics_are_preserved():
    text = "Hello, World! — नमस्ते।"
    assert normalize_text(text) == text


def test_whitespace_is_normalized_deterministically():
    assert normalize_text("  पानी \t\n  किताब  ") == "पानी किताब"
    assert normalize_text("पानी\u00a0किताब") == "पानी किताब"


def test_unsupported_normalization_version_is_rejected():
    with pytest.raises(ValueError):
        normalize_text("पानी", version="nfkc-fold-v9")


def test_candidate_hash_is_stable_and_versioned():
    h1 = candidate_hash("पानी", "ne")
    h2 = candidate_hash("पानी", "ne")
    assert h1 == h2
    assert len(h1) == 64
    # Different language, different identity.
    assert candidate_hash("पानी", "zh") != h1
    # Different normalization version must not collide.
    assert (
        candidate_hash("पानी", "ne", normalization_version=NORMALIZATION_VERSION) == h1
    )


def test_whitespace_variants_produce_the_same_hash():
    assert candidate_hash(normalize_text("पानी  किताब"), "ne") == candidate_hash(
        normalize_text("पानी किताब"), "ne"
    )


def test_request_fingerprint_changes_with_prompt_checksum():
    kwargs = dict(
        sense_key="fixture:1001",
        target_language="ne",
        provider="fake",
        model="fake-v1",
        prompt_version="p1",
    )
    a = request_fingerprint(prompt_checksum="aaa", **kwargs)
    b = request_fingerprint(prompt_checksum="bbb", **kwargs)
    assert a != b
    assert FINGERPRINT_VERSION == 1


def test_ids_are_derived_from_fingerprints():
    h = candidate_hash("पानी", "ne")
    assert candidate_id(h).startswith("cand_")
    assert candidate_id(h, "formal").endswith("_v-formal")
    assert candidate_id(h) != candidate_id(h, "informal")
