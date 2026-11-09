"""Mechanical validation of candidate text.

Mechanical only.  It never asserts linguistic correctness and it never
approves anything; a candidate that passes here is still ``needs_review``.
"""

from __future__ import annotations

import re

from ..domain.identity import normalize_text
from ..domain.models import SenseRef, ValidationResult


MAX_CHARS = 200
MIN_CHARS = 1

_LATIN = re.compile(r"[A-Za-z]")
_CYRILLIC = re.compile(r"[\u0400-\u04FF]")
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")

# Punctuation and joiners legitimately used in Nepali text.
_ALLOWED_ASCII = set(" .,!?;:'\"()-–—/") | {"\t", "\n"}
_ALLOWED_EXTRA = {0x200C, 0x200D, 0x00A0, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026}


def _is_allowed_char(ch: str) -> bool:
    code = ord(ch)
    if "\u0900" <= ch <= "\u097F":       # Devanagari, includes danda and digits
        return True
    if ch in _ALLOWED_ASCII:
        return True
    if code in _ALLOWED_EXTRA:
        return True
    return False


def validate_candidate(text: str, sense: SenseRef) -> ValidationResult:
    if not isinstance(text, str):
        return ValidationResult.failed("not_text", "candidate is not a string")

    stripped = text.strip()
    if len(stripped) < MIN_CHARS:
        return ValidationResult.failed("empty", "candidate is empty")
    if len(stripped) > MAX_CHARS:
        return ValidationResult.failed(
            "too_long", f"candidate is {len(stripped)} chars, limit {MAX_CHARS}"
        )

    if _CYRILLIC.search(stripped):
        return ValidationResult.failed(
            "cyrillic_in_output", "candidate contains Cyrillic letters"
        )
    if _LATIN.search(stripped):
        return ValidationResult.failed(
            "latin_in_output", "candidate contains Latin letters; not Devanagari-only"
        )

    if not _DEVANAGARI.search(stripped):
        return ValidationResult.failed(
            "no_devanagari", "candidate contains no Devanagari characters"
        )

    disallowed = sorted({ch for ch in stripped if not _is_allowed_char(ch)})
    if disallowed:
        shown = ", ".join(f"U+{ord(ch):04X}" for ch in disallowed[:5])
        return ValidationResult.failed(
            "script_mix", f"candidate contains characters outside Devanagari/allowed set: {shown}"
        )

    if normalize_text(stripped) == normalize_text(sense.gloss_en):
        return ValidationResult.failed(
            "echo_source", "candidate is identical to the English gloss"
        )

    return ValidationResult.passed()
